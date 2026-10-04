"""manager：ComfyUIManager——配置、多实例、执行编排、任务提交 + 模块级单例。

MCP 层（server/）只调用本层，不直接碰 aiohttp。
"""
from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from core.comfy_client import ComfyUIClient, check_workflow
from core.media import collect_outputs
from core.tasks import TaskManager
from core.workflow import inject_params, validate_api_workflow
from core.ws_session import execute_prompt
from schemas.models import ComfyUIConfig, ExecuteResult, TaskStatus

logger = logging.getLogger(__name__)


class ComfyUIError(Exception):
    """配置/登录等基础错误。"""


class ExecutionFailedError(ComfyUIError):
    """工作流执行失败（含中断）。"""

    def __init__(self, message: str, prompt_id: str = "", interrupted: bool = False):
        super().__init__(message)
        self.prompt_id = prompt_id
        self.interrupted = interrupted


def instance_supports_workflow(rules, workflow_name: str) -> tuple[bool, str]:
    """P5.13 工作流匹配规则：评估顺序固定 exclude → only → 都空 = 全支持。

    返回 (支持, 原因)；原因仅在不支持时非空。rules=None（未配置）= 全支持。
    条目为 fnmatch 通配符（大小写敏感）；内联 prompt（无工作流名）不过此门。
    """
    if rules is None:
        return True, ""
    for pat in rules.exclude:
        if fnmatch.fnmatchcase(workflow_name, pat):
            return False, f"命中 exclude 规则 {pat!r}"
    if rules.only and not any(
            fnmatch.fnmatchcase(workflow_name, p) for p in rules.only):
        return False, f"不命中 only 白名单 {list(rules.only)}"
    return True, ""


class ComfyUIManager:
    def __init__(self, config_path: str | Path = "config.json"):
        p = Path(config_path)
        if not p.is_file():
            raise ComfyUIError(f"配置文件不存在：{p}")
        self.config: ComfyUIConfig = ComfyUIConfig.model_validate(json.loads(
            p.read_text(encoding="utf-8")))
        if self.config.default_instance not in {i.name for i in self.config.comfyui_instances}:
            raise ComfyUIError(f"default_instance={self.config.default_instance!r} 不在实例列表中")
        self.base_dir = p.resolve().parent
        self._clients: dict[str, ComfyUIClient] = {}
        self.tasks = TaskManager()

    # ------------------------------------------------------------------
    # 配置 / 实例
    # ------------------------------------------------------------------
    @property
    def workflows_dir(self) -> Path:
        return self._path(self.config.workflows_dir)

    @property
    def output_dir(self) -> Path:
        return self._path(self.config.output_dir)

    def _path(self, name: str) -> Path:
        p = Path(name)
        return p if p.is_absolute() else self.base_dir / p

    def instance_names(self) -> list[str]:
        return [i.name for i in self.config.comfyui_instances]

    def client_for(self, name: Optional[str] = None) -> ComfyUIClient:
        name = name or self.config.default_instance
        inst = next((i for i in self.config.comfyui_instances if i.name == name), None)
        if inst is None:
            raise ComfyUIError(f"未知实例 {name!r}，可用：{self.instance_names()}")
        client = self._clients.get(name)
        if client is None:
            client = ComfyUIClient(inst)
            self._clients[name] = client
        return client

    async def status_all(self) -> list[dict]:
        import aiohttp
        results: list[dict] = []
        for name in self.instance_names():
            client = self.client_for(name)
            # 短超时：不可达实例快速失败，不拖垮整个 status（P5.8 回归）
            async with client.make_session(timeout_total=10) as session:
                try:
                    st = await client.get_status(session)
                except Exception as e:
                    st = {"name": name, "url": client.base_url,
                          "connected": False, "error": str(e)}
            results.append(st)
        return results

    # ------------------------------------------------------------------
    # 执行核心（各入口共用的唯一执行核心；P5.11 删除对外同步执行路径后，
    # 仅 _execute_task 后台 job 调用；任务状态统一由 _execute_task 记账）
    # ------------------------------------------------------------------
    async def _execute_once(
        self,
        instance: Optional[str],
        workflow: dict,
        params: Optional[dict[str, Any]] = None,
        workflow_name: str = "workflow",
        on_progress=None,
        total_timeout: float = 3600.0,
    ) -> ExecuteResult:
        client = self.client_for(instance)

        ok, err = validate_api_workflow(workflow)
        if not ok:
            raise ComfyUIError(f"工作流校验失败：{err}")
        wf, applied, unmatched = inject_params(workflow, params or {})
        if applied:
            logger.info("注入参数: %s", applied)
        if unmatched:
            logger.warning("未匹配参数（忽略）: %s", unmatched)

        t0 = time.time()
        async with client.make_session() as session:
            if not await client.login(session):
                raise ComfyUIError(f"实例 {client.instance.name} 登录失败")

            info = await client.object_info(session)
            if info:
                health = check_workflow(info, wf)
                if not health["executable"]:
                    detail = []
                    if health["nodes_missing"]:
                        detail.append("缺失节点: " + ", ".join(
                            f"{m['node_id']}({m['class_type']})"
                            for m in health["nodes_missing"][:5]))
                    if health["models_missing"]:
                        detail.append("缺失模型: " + "; ".join(
                            f"节点 {m['node_id']}.{m['param']}={m['value']}"
                            for m in health["models_missing"][:5]))
                        m0 = health["models_missing"][0]
                        if m0.get("available_sample"):
                            detail[-1] += (
                                f"（可用 {m0['available_count']} 个，示例：{m0['available_sample']}）")
                    raise ComfyUIError(
                        f"预检不通过（{client.instance.name}）：" + "；".join(detail))

            # P5.11 加固 e：每任务独立 client_id。服务端按 ?clientId= 注册 WS
            # 会话且事件只路由到该 slot（同 clientId 的新连接顶掉旧连接）；
            # 全进程共享 client_id 时并发任务 N-1 个收不到终态事件（newgoai
            # 实测 6 并发仅 1 完成，服务端 execution.py/server.py 证实路由机制）。
            task_client_id = str(uuid.uuid4())

            async def _submit() -> Optional[dict]:
                return await client.queue_prompt(session, wf,
                                                 client_id=task_client_id)

            ws_result = await execute_prompt(
                session, client, _submit, wf, on_progress=on_progress,
                total_timeout=total_timeout, task_client_id=task_client_id,
            )
            if ws_result.timed_out and ws_result.prompt_id:
                # P5.11 加固 b/f：分状态停止——已开跑 → /interrupt（带 prompt_id：
                # 改动版服务端仅当该 prompt 正在执行才精准中断，vanilla 忽略 body
                # 仍全局中断，多实例/共享实例并发安全）；仍在排队 → 删本 prompt
                # 队列项。两者失败均吞掉记日志，不影响终态落库。
                try:
                    if ws_result.started:
                        await client.interrupt(session, ws_result.prompt_id)
                    else:
                        await client.delete_from_queue(session, ws_result.prompt_id)
                except Exception:
                    logger.exception("[%s] 超时停止动作失败（prompt %s，已吞掉）",
                                     client.instance.name, ws_result.prompt_id)
            if not ws_result.success:
                raise ExecutionFailedError(
                    ws_result.error or "未知错误",
                    prompt_id=ws_result.prompt_id,
                    interrupted=ws_result.interrupted,
                )

            prefix = f"{client.instance.name}_{workflow_name}"
            paths, texts = await collect_outputs(
                session, client, ws_result.prompt_id, self.output_dir,
                prefix, text_outputs=ws_result.text_outputs,
            )
        elapsed = time.time() - t0
        logger.info("执行完成 %s：%d 个文件，%.1fs",
                    ws_result.prompt_id, len(paths), elapsed)
        return ExecuteResult(
            prompt_id=ws_result.prompt_id,
            instance=client.instance.name,
            outputs=paths,
            text_outputs=texts,
            progress_nodes=ws_result.progress_nodes,
            elapsed=elapsed,
        )

    async def workflow_health(self, wf: dict, workflow_name: str = "",
                              instance: Optional[str] = None) -> dict:
        """P5.8：工作流在指定实例上的健康检查（任何失败都降级，绝不抛）。

        返回 {checked, instance, reason?} + check_workflow 结果
        （nodes_missing / models_missing / executable）。
        """
        name = instance or self.config.default_instance
        try:
            client = self.client_for(instance)
        except ComfyUIError as e:
            return {"checked": False, "instance": name, "reason": f"未知实例：{e}"}
        try:
            async with client.make_session(timeout_total=30) as session:
                if not await client.login(session):
                    return {"checked": False, "instance": client.instance.name,
                            "reason": "登录失败"}
                info = await client.object_info(session)
                if not info:
                    return {"checked": False, "instance": client.instance.name,
                            "reason": "object_info 不可用"}
                res = check_workflow(info, wf)
        except Exception as e:
            logger.warning("[health] %s 检查异常：%s", name, e)
            return {"checked": False, "instance": name,
                    "reason": f"检查异常：{e}"}
        res["checked"] = True
        res["instance"] = client.instance.name
        return res

    # ------------------------------------------------------------------
    # 路由（P5.13）：recommended_instance = 符合要求（规则∩可达）且排队最少
    # 仅 describe 使用——实例选择由调用方完成（submit/upload 的 instance 必填），
    # 服务端不自动路由。所有探测降级：不可达实例标记候选、不参与打分。
    # ------------------------------------------------------------------
    async def route_workflow(self, wf: dict, workflow_name: str) -> dict:
        """路由块：recommended_instance + reason + candidates + as_of。

        打分 = routing.weights.pending×queue_pending + running×queue_running，
        候选（supported ∩ reachable）中取最低分；平局 → default_instance。
        全不可达/全被规则排除 → recommended_instance=None + reason。
        """
        weights = self.config.routing.weights
        default = self.config.default_instance
        candidates: list[dict[str, Any]] = []
        to_probe: list[tuple[Any, dict]] = []
        for cfg in self.config.comfyui_instances:
            cand: dict[str, Any] = {
                "instance": cfg.name, "supported": True, "excluded_reason": "",
                "reachable": None, "queued": None, "running": None,
                "health": None, "score": None,
            }
            if workflow_name and workflow_name != "inline":
                ok, reason = instance_supports_workflow(
                    cfg.workflow_rules, workflow_name)
                if not ok:
                    cand.update(supported=False, excluded_reason=f"规则：{reason}")
                    candidates.append(cand)
                    continue
            to_probe.append((cfg, cand))
            candidates.append(cand)
        if to_probe:
            probes = await asyncio.gather(*(
                self._probe_instance(cfg, wf, workflow_name)
                for cfg, _ in to_probe))
            for (_cfg, cand), probe in zip(to_probe, probes):
                cand.update(reachable=probe["reachable"],
                            queued=probe["queued"],
                            running=probe["running"],
                            health=probe["health"])
                if probe["reachable"]:
                    cand["score"] = round(
                        weights.pending * probe["queued"]
                        + weights.running * probe["running"], 4)
                else:
                    cand["excluded_reason"] = f"不可达：{probe['error']}"
        pool = [c for c in candidates if c["supported"] and c["reachable"] is True]
        if pool:
            scored = sorted(pool, key=lambda c: (c["score"], c["instance"] != default))
            recommended = scored[0]["instance"]
            reason = (f"{len(pool)} 个符合要求的实例中排队最少"
                      f"（score = {weights.pending:g}×pending + "
                      f"{weights.running:g}×running，取最低）")
        else:
            recommended = None
            reason = ("无符合要求的可达实例："
                      + "；".join(f"{c['instance']}({c['excluded_reason']})"
                                  for c in candidates))
        return {"recommended_instance": recommended, "reason": reason,
                "candidates": candidates,
                "as_of": time.strftime("%Y-%m-%d %H:%M:%S")}

    async def _probe_instance(self, cfg, wf: dict, workflow_name: str) -> dict:
        """路由探测单实例：可达性 + 队列长度 + health（全降级，绝不抛）。

        返回 {reachable, queued, running, health, error}。
        """
        out: dict[str, Any] = {"reachable": False, "queued": None,
                               "running": None, "health": None, "error": ""}
        client = self.client_for(cfg.name)
        try:
            async with client.make_session(timeout_total=10) as session:
                if not await client.login(session):
                    out["error"] = "登录失败"
                    return out
                queue = await client.get_queue(session)
                if queue is None:
                    out["error"] = "/queue 不可用（可能登录失效）"
                    return out
                out["reachable"] = True
                out["queued"] = len(queue.get("queue_pending", []))
                out["running"] = len(queue.get("queue_running", []))
        except Exception as e:
            out["error"] = str(e)
            return out
        out["health"] = await self.workflow_health(wf, workflow_name, cfg.name)
        return out

    # ------------------------------------------------------------------
    # 异步任务（唯一执行入口）
    # ------------------------------------------------------------------
    async def submit_workflow(self, instance: Optional[str], workflow: dict,
                              params: Optional[dict[str, Any]] = None,
                              workflow_name: str = "workflow",
                              timeout_s: float = 3600.0) -> str:
        # P5.13：instance 必填（实例选择由调用方完成，取 describe 的
        # routing.recommended_instance）；显式点名 = 规则硬拒（不匹配立即报错，
        # 不排队后炸）。内联 prompt（"inline"）无名字，不受实例规则限制。
        if not instance:
            raise ComfyUIError("instance 必填：先用 describe_workflow 取 "
                               "routing.recommended_instance 再提交")
        inst = next((i for i in self.config.comfyui_instances
                     if i.name == instance), None)
        if inst is None:
            raise ComfyUIError(f"未知实例 {instance!r}，可用：{self.instance_names()}")
        if workflow_name and workflow_name != "inline":
            ok_rule, reason = instance_supports_workflow(
                inst.workflow_rules, workflow_name)
            if not ok_rule:
                raise ComfyUIError(
                    f"实例 {instance!r} 不支持工作流 {workflow_name!r}：{reason}")
        ok, err = validate_api_workflow(workflow)
        if not ok:
            raise ComfyUIError(f"工作流校验失败：{err}")
        name = instance
        record = await self.tasks.create(name, workflow_name)
        job = asyncio.create_task(self._execute_task(record.task_id, name, workflow,
                                                     params, workflow_name, timeout_s))
        await self.tasks.attach_job(record.task_id, job)
        logger.info("[tasks] 已提交 %s（%s / %s，总超时 %ss 含排队等待）",
                    record.task_id, name, workflow_name, f"{timeout_s:.0f}")
        return record.task_id

    async def _execute_task(self, task_id: str, instance: str, workflow: dict,
                            params: Optional[dict[str, Any]], workflow_name: str,
                            timeout_s: float = 3600.0) -> None:
        async def on_progress(node_id, status, prompt_id, error=None):
            if status == "started":
                rec = self.tasks.get(task_id)
                if rec:
                    rec.prompt_id = prompt_id
            if node_id:
                await self.tasks.update_progress(task_id, node_id)

        try:
            result = await self._execute_once(
                instance, workflow, params, workflow_name, on_progress=on_progress,
                total_timeout=timeout_s,
            )
            await self.tasks.finish(task_id, TaskStatus.COMPLETED,
                                    prompt_id=result.prompt_id,
                                    outputs=result.outputs,
                                    text_outputs=result.text_outputs,
                                    elapsed=result.elapsed)
        except asyncio.CancelledError:
            await self.tasks.finish(task_id, TaskStatus.CANCELLED,
                                    error="用户取消")
            raise
        except ExecutionFailedError as e:
            status = TaskStatus.CANCELLED if e.interrupted else TaskStatus.FAILED
            await self.tasks.finish(task_id, status, prompt_id=e.prompt_id,
                                    error=str(e))
        except ComfyUIError as e:
            await self.tasks.finish(task_id, TaskStatus.FAILED, error=str(e))
        except Exception as e:
            logger.exception("[tasks] %s 未预期异常", task_id)
            await self.tasks.finish(task_id, TaskStatus.FAILED,
                                    error=f"执行异常：{e}")

    async def cancel_task(self, task_id: str) -> tuple[bool, str]:
        record = self.tasks.get(task_id)
        if record is None:
            return False, "任务不存在"
        if record.status == TaskStatus.PENDING:
            if record.prompt_id:
                # P5.11 加固 a：prompt 在 WS 建连时已进远端队列，不删则远端稍后照常
                # 执行（任务显示 CANCELLED 但 GPU 真跑）。先删远端队列项再取消本地
                # job；删失败吞掉记日志（竞态：已开始执行的 prompt 删不生效，记录
                # 会转 RUNNING，用户可再 cancel 走 /interrupt）。
                try:
                    client = self.client_for(record.instance)
                    async with client.make_session(timeout_total=20) as session:
                        if await client.login(session):
                            okq = await client.delete_from_queue(session, record.prompt_id)
                            logger.info("[tasks] %s 删远端队列 prompt %s：%s",
                                        task_id, record.prompt_id[:12],
                                        "成功" if okq else "未命中（可能已开始执行）")
                        else:
                            logger.warning("[tasks] %s 登录失败，无法删远端队列"
                                           "（prompt %s 可能继续执行）",
                                           task_id, record.prompt_id)
                except Exception:
                    logger.exception("[tasks] %s 删远端队列失败（已吞掉）", task_id)
            if await self.tasks.cancel_job(task_id):
                return True, "已取消（排队阶段）"
            return False, "任务已不在排队"
        if record.status == TaskStatus.RUNNING:
            client = self.client_for(record.instance)
            import aiohttp
            async with client.make_session(timeout_total=20) as session:
                if not await client.login(session):
                    return False, "登录失败，无法中断"
                ok = await client.interrupt(session, record.prompt_id)
            if ok:
                return True, "已发送 /interrupt（WS 监听将确认中断）"
            return False, "中断请求失败"
        return False, f"任务已是终态 {record.status.value}"

    # ------------------------------------------------------------------
    # 上传
    # ------------------------------------------------------------------
    async def upload_image(self, instance: Optional[str], file_path: str,
                           image_type: str = "input", overwrite: bool = True) -> dict:
        # P5.13：instance 必填——媒体文件实例局部，必须与 submit 的 instance 一致
        # （取 describe 的 routing.recommended_instance），否则 submit 时目标
        # 实例没有该文件，直接 file not found。
        if not instance:
            raise ComfyUIError("instance 必填：媒体文件实例局部，须与 submit "
                               "同一实例（取 describe 的 routing.recommended_instance）")
        client = self.client_for(instance)
        import aiohttp
        async with client.make_session(timeout_total=120) as session:
            if not await client.login(session):
                raise ComfyUIError(f"实例 {client.instance.name} 登录失败")
            result = await client.upload_image(session, file_path, image_type, overwrite)
            if result is None:
                raise ComfyUIError("上传失败（详见日志）")
            return result


# ----------------------------------------------------------------------
# 模块级单例
# ----------------------------------------------------------------------
_manager: Optional[ComfyUIManager] = None
_manager_lock = threading.Lock()


def get_manager(config_path: str | Path = "config.json") -> ComfyUIManager:
    """进程内单例；重复调用返回同一实例（config 路径变化则重建）。"""
    global _manager
    with _manager_lock:
        if _manager is None or _manager._config_path != str(config_path):
            m = ComfyUIManager(config_path)
            m._config_path = str(config_path)
            _manager = m
        return _manager
