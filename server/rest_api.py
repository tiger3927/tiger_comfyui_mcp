"""REST 端点：/api/* + /files/*。与 MCP 工具调同一批 core 方法。"""
from __future__ import annotations

import logging
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.manager import ComfyUIError, ComfyUIManager, workflow_in_whitelist
from core.workflow import (
    load_named_workflow,
    parse_workflow_params,
)

logger = logging.getLogger(__name__)

# ── 媒体上传（唯一上传通道）防护 ──────────────────────────────────────
# 单文件上限：H3 类视频参考可能较大，取 200MB（超过即 413，流式边收边判）
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
# 票据上传的每 IP 限流（滑动窗口 1 小时；Bearer 通道不在此列，门户自有风控）
_UPLOAD_WINDOW_S = 3600.0
_UPLOAD_MAX_PER_IP = 30
_ip_uploads: dict[str, list[float]] = {}
_upload_lock = threading.Lock()


class TaskRequest(BaseModel):
    workflow_name: str = ""
    prompt_json: str = ""
    params: Optional[dict[str, Any]] = None
    instance: str = ""  # P5.13：必填（取 describe 的 routing.recommended_instance）；
                        # 空/缺失 → manager 抛 ComfyUIError → 400
    timeout_s: float = 3600.0


def _wf(mgr: ComfyUIManager, workflow_name: str, prompt_json: str) -> tuple[dict, str]:
    if workflow_name:
        return load_named_workflow(mgr.workflows_dir, workflow_name), workflow_name
    if prompt_json:
        import json
        return json.loads(prompt_json), "inline"
    raise HTTPException(400, "必须提供 workflow_name 或 prompt_json")


def build_router(mgr: ComfyUIManager) -> APIRouter:
    r = APIRouter(prefix="/api")

    @r.get("/status")
    async def status():
        return {"instances": await mgr.status_all()}

    @r.get("/workflows")
    async def workflows():
        # P5.19：与 MCP list_workflows 同源（目录 ∩ 顶层白名单 + instances 标注）
        return {"workflows": await mgr.list_workflows_gated()}

    @r.get("/workflows/{name}")
    async def workflow_detail(name: str, instance: str = Query("")):
        ok_wl, reason_wl = workflow_in_whitelist(
            await mgr.config_provider.get_whitelist(), name)
        if not ok_wl:
            # 404 不泄露"存在但未放行"（与"文件不存在"同态，P5.19 fail-closed）
            raise HTTPException(404, f"工作流不存在或未列入白名单：{name}（{reason_wl}）")
        try:
            wf = load_named_workflow(mgr.workflows_dir, name)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        params = parse_workflow_params(wf)
        health = await mgr.workflow_health(wf, name, instance or None)
        routing = await mgr.route_workflow(wf, name)  # P5.13：与 MCP describe 同源
        return {"name": name,
                "inputs": [p.to_dict() for p in params if p.kind == "input"],
                "outputs": [p.to_dict() for p in params if p.kind == "output"],
                "nodes": {nid: {"class_type": (n or {}).get("class_type", ""),
                                "title": ((n or {}).get("_meta") or {}).get("title", "")}
                          for nid, n in wf.items()},
                "health": health,
                "routing": routing,
                "stats": mgr.tasks.workflow_stats(name)}

    @r.post("/tasks", status_code=202)
    async def create_task(request: Request, body: TaskRequest):
        """唯一执行入口：立即返回 task_id，用 GET /api/tasks/{id} 轮询。"""
        # 用户积分 token：从 Authorization: Bearer 读（Task-WWW §5.3；AuthMiddleware 已校验有效）
        _auth = request.headers.get("Authorization", "")
        token = _auth.removeprefix("Bearer ").strip() if _auth.startswith("Bearer ") else ""
        try:
            wf, wf_name = _wf(mgr, body.workflow_name, body.prompt_json)
            task_id = await mgr.submit_workflow(
                instance=body.instance, workflow=wf,
                params=body.params, workflow_name=wf_name,
                timeout_s=body.timeout_s,
                user_token=token,
            )
        except ComfyUIError as e:
            raise HTTPException(400, str(e))
        return {"task_id": task_id}

    @r.get("/tasks/{task_id}")
    async def task_status(task_id: str):
        # P5.20：与 MCP 同源 task_view（outputs + outputs_urls 下载直链）
        view = mgr.task_view(task_id)
        if view is None:
            raise HTTPException(404, f"任务不存在：{task_id}")
        return view

    @r.post("/tasks/{task_id}/cancel")
    async def task_cancel(task_id: str):
        ok, message = await mgr.cancel_task(task_id)
        if not ok and "不存在" in message:
            raise HTTPException(404, message)
        return {"ok": ok, "message": message}

    @r.post("/upload")
    async def upload(request: Request,
                     file: UploadFile = File(...),
                     file_type: str = Query("input"),
                     instance: str = Query(""),
                     ticket: str = Query("")):
        """媒体上传唯一通道（MCP 层无上传工具，文件字节走 HTTP 不进模型上下文）。

        鉴权二选一：
        - Bearer（AuthMiddleware 已验）：门户用户通道
        - ticket：一次性上传票据（MCP comfyui_request_upload_ticket 签发，
          短时效单次、绑定 instance/file_type，权限仅限本次上传）
        """
        # P5.13：instance 必填（与 submit 同一实例；取 describe 的
        # routing.recommended_instance）——参数错误归 400 而非 502
        if not instance:
            raise HTTPException(400, "instance 查询参数必填"
                                     "（与 submit 同一实例，取 describe 的 "
                                     "routing.recommended_instance）")
        if ticket.strip():
            ok, err = mgr.tickets.consume(ticket.strip(), instance, file_type)
            if not ok:
                raise HTTPException(403, f"上传票据校验失败：{err}")
            ip = request.client.host if request.client else "-"
            now = time.time()
            with _upload_lock:
                window = [t for t in _ip_uploads.get(ip, [])
                          if now - t < _UPLOAD_WINDOW_S]
                if len(window) >= _UPLOAD_MAX_PER_IP:
                    raise HTTPException(
                        429, f"上传过于频繁（每 IP 每 {_UPLOAD_WINDOW_S / 3600:.0f} "
                             f"小时上限 {_UPLOAD_MAX_PER_IP} 次），请稍后再试")
                window.append(now)
                _ip_uploads[ip] = window
        suffix = Path(file.filename or "upload.png").suffix or ".png"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            # 流式落盘 + 体积上限（不在内存里攒整个文件）
            written = 0
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        413, f"文件超过单文件上限 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB")
                tmp.write(chunk)
            tmp_path = tmp.name
        try:
            result = await mgr.upload_image(instance, tmp_path,
                                            image_type=file_type)
        except ComfyUIError as e:
            raise HTTPException(502, str(e))
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        return result

    return r


def files_router(mgr: ComfyUIManager) -> APIRouter:
    r = APIRouter(prefix="/files")

    @r.get("/{path:path}")
    async def download(path: str):
        """下载 output/ 产物（路径穿越防护）。"""
        base = mgr.output_dir.resolve()
        target = (base / path).resolve()
        if base != target and base not in target.parents:
            raise HTTPException(403, "路径越界")
        if not target.is_file():
            raise HTTPException(404, f"文件不存在：{path}")
        return FileResponse(target, filename=target.name)

    return r
