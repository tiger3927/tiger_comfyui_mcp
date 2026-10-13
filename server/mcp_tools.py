"""MCP 工具注册（8 个）。只调 core/，不含业务逻辑。

上传通道 REST 化：本层无上传工具——媒体文件一律用
comfyui_request_upload_ticket 取一次性票据后 REST POST /api/upload
multipart 直传（文件字节走 HTTP，不进模型上下文）。
mcp 2.x：MCPServer + @srv.tool()（T0.3 实测，原 FastMCP 已改名）。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import functools

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError

from core.manager import ComfyUIError, ComfyUIManager, workflow_in_whitelist
from core.workflow import (
    load_named_workflow,
    parse_workflow_params,
)
from portal.errors import PortalError

logger = logging.getLogger(__name__)


def _resolve_workflow(mgr: ComfyUIManager, workflow_name: str,
                      prompt_json: str) -> tuple[dict, str]:
    """工作流来源二选一：名称 或 内联 JSON。返回 (workflow, 名称)。"""
    if workflow_name:
        wf = load_named_workflow(mgr.workflows_dir, workflow_name)
        return wf, workflow_name
    if prompt_json:
        wf = json.loads(prompt_json)
        return wf, "inline"
    raise ComfyUIError("必须提供 workflow_name 或 prompt_json（内联 JSON）")


def mcp_tool_guard(fn):
    """MCP 工具错误守卫：可预期的业务错误（ComfyUIError：instance 必填/未知实例/
    规则硬拒/任务不存在/工作流不存在等；PortalError：匿名被关/积分不足/token 上限
    等在途上限）→ ToolError（is_error=True + 原始消息进 content，LLM 直接可读）；
    未捕获的其他异常仍走 SDK 的 UnexpectedToolError（服务端 ERROR 日志带
    traceback）。functools.wraps 保留签名/文档（工具 schema 由 inspect.signature
    沿 __wrapped__ 生成，参数必填性不受影响）。"""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except ComfyUIError as e:
            raise ToolError(str(e)) from e
        except PortalError as e:
            raise ToolError(f"[{e.code}] {e.message}") from e

    return wrapper


def _bearer_token_from_ctx(ctx: Context | None) -> Optional[str]:
    """MCP 请求头 Authorization: Bearer <token> → 明文 token（无则 None）。

    IDE/客户端在 MCP 连接配置里配了 Bearer 头时（AuthMiddleware 已用它过
    /mcp 鉴权门禁），提交工具 token 参数缺省即回退用它做门户 precheck/计费
    归属——否则请求头身份与任务归属脱节，匿名被关时必然 AnonymousBlocked。
    ctx.headers 仅 HTTP 传输有值（stdio 为 None），取不到一律 None。"""
    if ctx is None:
        return None
    headers = ctx.headers
    if not headers:
        return None
    auth = headers.get("authorization")
    if not auth:
        return None
    auth = auth.strip()
    if not auth.lower().startswith("bearer "):
        return None
    return auth[7:].strip() or None


def build_mcp_server(mgr: ComfyUIManager) -> MCPServer:
    srv = MCPServer(
        name="tiger-comfyui-mcp",
        description="ComfyUI 多实例工作流执行/解析工具（MCP + REST 双入口）",
    )

    @srv.tool()
    async def comfyui_user_guide() -> dict:
        """获取本服务使用指南（Markdown：8 个 MCP 工具 + REST WebAPI 全貌）。

        建议开始任何任务前先调用本工具：含认证、标准流程、媒体输入约定、
        轮询间隔、取消/超时语义、REST 端点与 curl 示例、错误码排障、调用纪律。
        指南文件：server/user-guide.md（与 REST /files、/api 端点同源维护）。
        正文不含任何固定地址；返回末尾按 config 的 server.public_base_url
        动态注入“7. 本部署地址与直连方式”（实际 base + 上传/下载 curl）。
        """
        text = Path(__file__).with_name("user-guide.md").read_text(encoding="utf-8")
        base = (mgr.config.server.public_base_url or "").rstrip("/")
        if base:
            text += (
                "\n## 7. 本部署地址与直连方式（由 config `server.public_base_url` 动态注入）\n\n"
                f"本服务实际地址为 `{base}`（正文中 `$BASE` / `http://<host>:<port>` "
                "均指此值，§4 的 REST 示例替换后即可直接执行）。两个高频直连用法：\n\n"
                "1. **文件上传**（媒体素材；先用 MCP 只读工具 "
                "`comfyui_request_upload_ticket(instance)` 取一次性票据）：\n"
                f"   ```\n"
                f"   curl -F \"file=@<本地文件>\" \"{base}/api/upload?file_type=input&instance=<实例>&ticket=<票据>\"\n"
                f"   # → {{\"name\": \"tmpxxxxxx.png\", ...}}（用返回的 name 作 INPUT_*_FILE 参数值）\n"
                f"   ```\n"
                "   （持有门户 Bearer token 时可免票据：同一 URL 加 "
                "`-H \"Authorization: Bearer <token>\"`）\n\n"
                "2. **产物下载**（免认证；文件名来自 `task_status` 的 "
                "`outputs_urls` / `outputs`）：\n"
                f"   ```\n"
                f"   curl -o out.mp3 \"{base}/files/<文件名>\"\n"
                f"   ```\n"
            )
        return {"guide_md": text, "chars": len(text)}

    @srv.tool()
    async def comfyui_status() -> dict:
        """各 ComfyUI 实例的连接/登录状态与队列负载。"""
        return {"instances": await mgr.status_all()}

    @srv.tool()
    async def comfyui_list_workflows() -> dict:
        """列出可用工作流及 .md 摘要。

        P5.19：仅返回 config.allowed_workflows 白名单内的工作流（fail-closed：
        白名单为空 = 全不放行；目录有文件 ≠ 可用）。每项附 instances=实例规则
        放行的实例名（静态，不含可达性），可据此直接选实例。"""
        return {"workflows": await mgr.list_workflows_gated()}

    @srv.tool()
    @mcp_tool_guard
    async def comfyui_describe_workflow(name: str, instance: str = "") -> dict:
        """解析工作流 + 实例健康检查 + 路由推荐 + 内存执行统计。

        返回 inputs/outputs/nodes 及三块：
        - health: executable（未发现阻塞项，必要非充分）/ nodes_missing（自定义节点未安装）/
          models_missing（模型权重 COMBO 字面量不在该实例选项列表）/
          inputs_placeholder_missing（输入媒体占位示例缺失，纯信息项，不影响 executable，
          提交时上传实际文件即可）；
          实例不可达/登录失败时降级为 {checked: false, reason}，本地解析照常返回
        - routing（P5.13 路由推荐）: recommended_instance = 符合要求（config 规则∩可达）
          且排队最少（加权最低分，平局→default_instance）；candidates 列出每个实例的
          supported/excluded_reason/queued/running/health/score；全不可达时为 null + reason。
          **票据申请（request_upload_ticket）/ submit_task 的 instance 参数必填——
          用这里的 recommended_instance**
        - stats: 本服务进程内存统计（重启清零；终态受 24h/200 条裁剪）：
          total/completed/failed/cancelled/in_progress/success_rate +
          recent_failures（最近 5 类失败，按 error 去重合并：error/count/last_at，
          error 截断 300 字符）——调用前可据此避坑

        Args:
            name: 工作流名称（workflows/ 下 json 文件名，不含扩展名）
            instance: 健康检查用实例名（默认 config 的 default_instance）

        Returns:
            {
              "name": str,
              "inputs":  [{name, label, type, required, default, hint}, ...],  # 可注入参数；hint 提示用法（如先上传填 INPUT_*_FILE）
              "outputs": [{name, label, type, required, default, hint}, ...],  # 产出物
              "nodes":   {node_id: {class_type, title}, ...},                  # 节点清单
              "health":  正常 {checked: true, instance, executable: bool,
                              nodes_missing: [类名...],
                              models_missing: [{node, class_type, param, value,
                                               available_sample, available_count}...],
                              inputs_placeholder_missing: [同上结构]...}       # 占位示例缺失，不影响 executable
                         降级 {checked: false, instance, reason},            # 实例不可达/登录失败
              "routing": {recommended_instance: str|null, reason: str,
                          candidates: [{instance, supported, excluded_reason,
                                       reachable, queued, running,
                                       health: <同顶层 health 结构>|null,
                                       score: float|null}, ...],
                          as_of: "YYYY-MM-DD HH:MM:SS"},                     # 全实例路由推荐
              "stats":   {total, completed, failed, cancelled, in_progress,
                          success_rate,
                          recent_failures: [{error, count, last_at}, ...]}   # 内存统计，避坑
            }
        """
        ok_wl, reason_wl = workflow_in_whitelist(
            await mgr.config_provider.get_whitelist(), name)
        if not ok_wl:
            raise ComfyUIError(f"工作流 {name!r} 未通过全局白名单：{reason_wl}")
        wf = load_named_workflow(mgr.workflows_dir, name)
        params = parse_workflow_params(wf)
        nodes = {nid: {"class_type": (n or {}).get("class_type", ""),
                       "title": ((n or {}).get("_meta") or {}).get("title", "")}
                 for nid, n in wf.items()}
        health = await mgr.workflow_health(wf, name, instance or None)
        routing = await mgr.route_workflow(wf, name)
        stats = mgr.tasks.workflow_stats(name)
        return {"name": name,
                "inputs": [p.to_dict() for p in params if p.kind == "input"],
                "outputs": [p.to_dict() for p in params if p.kind == "output"],
                "nodes": nodes,
                "health": health,
                "routing": routing,
                "stats": stats}

    @srv.tool()
    @mcp_tool_guard
    async def comfyui_submit_task(instance: str,
                                  workflow_name: str = "",
                                  prompt_json: str = "",
                                  params: Optional[dict[str, Any]] = None,
                                  timeout_s: float = 3600.0,
                                  token: Optional[str] = None,
                                  ctx: Optional[Context] = None) -> dict:
        """提交工作流执行（唯一执行入口），立即返回 task_id。

        instance 必填：用 comfyui_describe_workflow 返回的 routing.recommended_instance
        （符合要求 ∩ 排队最少）；点名实例不匹配其 config 规则（workflow_rules）时
        立即报错（硬拒，不排队后炸）。

        用 comfyui_task_status 轮询进度（建议间隔 10–30s；completed 后其返回中
        含 outputs 本地文件路径与 text_outputs），用 comfyui_cancel_task 取消
        （排队中=删远端队列，执行中=/interrupt）。

        媒体文件上传（MCP 无上传工具）：用 comfyui_request_upload_ticket(instance)
        取一次性票据 → 本地执行其返回的 curl 命令（REST multipart 直传，文件字节
        走 HTTP 不进模型上下文）→ 用返回的 name 注入 INPUT_*_FILE 参数（须同一实例）。
        预检发现媒体文件缺失时，本工具报错会直接内嵌票据与 curl 命令。

        Args:
            instance: 实例名（必填，不能为空；取 describe 的 routing.recommended_instance）
            workflow_name: 工作流名（与 prompt_json 二选一）
            prompt_json: 内联 API 格式工作流 JSON 字符串（内联无名字，不受实例规则限制）
            params: 参数注入，如 {"INPUT_POSITIVE_TEXT": "...", "seed": 42}；
                媒体参数为文件名（按上述票据+REST 流程上传取 name，
                如 {"INPUT_IMAGE_FILE": "tmpxxxxxx.png"}，须同一实例）
            timeout_s: 总超时秒（默认 3600，含排队等待；超时后按状态停止并记 FAILED）
            token: 用户积分 token（可选）；传入则提交前做预检（余额/token 上限/在途
                上限），不足即拒。不传时回退 MCP 请求头 Authorization: Bearer <token>
                （客户端连接配置里配的 Bearer），仍无=匿名（仅当服务允许匿名任务时）
        """
        if not token:
            token = _bearer_token_from_ctx(ctx)
        wf, wf_name = _resolve_workflow(mgr, workflow_name, prompt_json)
        task_id = await mgr.submit_workflow(
            instance=instance, workflow=wf, params=params,
            workflow_name=wf_name, timeout_s=timeout_s,
            user_token=token,
        )
        return {"task_id": task_id,
                "hint": "用 comfyui_task_status 轮询（建议 10–30s 间隔，图片和语音生成类10s间隔，视频生成类20s间隔，视频类多次轮询还在排队扩展到30s间隔），"
                        "comfyui_cancel_task 取消"}

    @srv.tool()
    @mcp_tool_guard
    async def comfyui_task_status(task_id: str) -> dict:
        """查任务进度（节点级）。

        completed 后返回：outputs（本服务机上产物绝对路径，MCP 客户端与
        服务机同机时可直接读）、**outputs_urls（产物公网下载直链：
        http://<host>:<port>/files/<文件名>，GET 即下载、无需任何认证——
        跨机器调用者一律用这些链接取产物）**、text_outputs。

        Args:
            task_id: comfyui_submit_task 返回的任务 ID
        """
        view = mgr.task_view(task_id)
        if view is None:
            raise ComfyUIError(f"任务不存在：{task_id}")
        return view

    @srv.tool()
    async def comfyui_cancel_task(task_id: str) -> dict:
        """取消任务（pending 直接取消，running 走 /interrupt）。

        Args:
            task_id: 任务 ID
        """
        ok, message = await mgr.cancel_task(task_id)
        return {"ok": ok, "message": message}

    @srv.tool()
    @mcp_tool_guard
    async def comfyui_request_upload_ticket(instance: str,
                                            file_type: str = "input") -> dict:
        """签发一次性媒体上传票据（上传唯一通道 = REST 直传，MCP 无上传工具）。

        媒体文件（INPUT_*_FILE 参数的图片/音频/视频）一律三步：
          1. 本工具取票据（短时效、单次有效、绑定 instance）
          2. 本地执行返回的 curl 命令（REST multipart 直传，文件字节走 HTTP
             不进模型上下文——绝不把文件内容塞进对话/MCP 参数）
          3. 用返回的 name 作为 INPUT_*_FILE 参数值调用 comfyui_submit_task
             （name 为服务端随机 tmp 名，必须引用返回值；上传与执行须同一实例）

        Args:
            instance: 实例名（必填；与 submit_task 同一实例，取 describe 的
                routing.recommended_instance）
            file_type: 目标文件夹 input / output / temp（默认 input）
        """
        inst = instance.strip()
        if not inst:
            raise ComfyUIError("instance 必填（与 submit_task 同一实例，"
                               "取 describe 的 routing.recommended_instance）")
        # 未知实例/已禁用实例 → ComfyUIError（禁用实例不签发上传票据）
        await mgr.require_active_instance(inst)
        t = mgr.tickets.issue(inst, file_type or "input")
        base = (mgr.config.server.public_base_url or "").rstrip("/")
        curl = (f'curl -F "file=@<本地文件>" "{base}/api/upload'
                f'?file_type={t["file_type"]}&instance={inst}&ticket={t["ticket"]}"')
        return {"ticket": t["ticket"], "instance": inst,
                "file_type": t["file_type"], "expires_in": t["expires_in"],
                "curl": curl,
                "hint": ("上传返回 {name, subfolder, type}；name 为服务端随机 tmp 名，"
                         "用它作 INPUT_*_FILE 参数值重新 comfyui_submit_task（同一实例）")}

    return srv
