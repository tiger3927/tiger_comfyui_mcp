"""MCP 工具注册（8 个）。只调 core/，不含业务逻辑。

mcp 2.x：MCPServer + @srv.tool()（T0.3 实测，原 FastMCP 已改名）。
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Optional

import functools

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from core.manager import ComfyUIError, ComfyUIManager, workflow_in_whitelist
from core.workflow import (
    load_named_workflow,
    parse_workflow_params,
)

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# b64 上传载荷解包（P5.7）：filename 参数 > data-URI MIME > 前缀嗅探 > 默认 .png
# ComfyUI /upload/image 按 multipart filename 原样落盘，扩展名由下游节点过滤
# ----------------------------------------------------------------------
_SNIFF_EXTS = (
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif",
    ".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus", ".aac",
    ".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v", ".wmv", ".mpg", ".mpeg",
)
_MIME_EXTS = {
    # 图片
    "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
    "image/gif": ".gif", "image/bmp": ".bmp", "image/tiff": ".tiff",
    # 音频
    "audio/wav": ".wav", "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
    "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/ogg": ".ogg",
    "audio/opus": ".opus", "audio/flac": ".flac", "audio/x-flac": ".flac",
    "audio/aac": ".aac", "audio/x-aac": ".aac",
    # 视频
    "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
    "video/x-matroska": ".mkv", "video/x-msvideo": ".avi",
    "video/x-ms-wmv": ".wmv", "video/mpeg": ".mpg", "video/x-m4v": ".m4v",
}


def _decode_b64_payload(raw: str) -> tuple[bytes, Optional[str]]:
    """解包 b64 载荷：裸 base64 或 data-URI（data:<mime>;base64,...）。

    返回 (解码字节, MIME)；裸 base64 时 MIME 为 None。
    """
    raw = raw.strip()
    if raw.lower().startswith("data:"):
        head, _, payload = raw.partition(",")
        mime = head[5:].split(";", 1)[0].strip().lower() or None
        return base64.b64decode(payload), mime
    return base64.b64decode(raw), None


def _resolve_b64_suffix(filename: str, raw: str, mime: Optional[str]) -> str:
    """确定 b64 上传的落盘后缀：filename 参数 > data-URI MIME > 前缀嗅探 > .png。"""
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix:
            return suffix
        logger.warning("[upload] filename=%r 无后缀，转入后续推断", filename)
    if mime:
        ext = _MIME_EXTS.get(mime)
        if ext:
            return ext
        logger.warning("[upload] 未识别 MIME %s，转入后续推断", mime)
    for ext in _SNIFF_EXTS:
        if ext in raw[:64].lower():
            return ext
    logger.warning("[upload] 无法识别文件类型，默认 .png（建议显式传 filename）")
    return ".png"


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
    规则硬拒/任务不存在/工作流不存在等）→ ToolError（is_error=True + 原始消息
    进 content，LLM 直接可读）；未捕获的其他异常仍走 SDK 的 UnexpectedToolError
    （服务端 ERROR 日志带 traceback）。functools.wraps 保留签名/文档（工具 schema
    由 inspect.signature 沿 __wrapped__ 生成，参数必填性不受影响）。"""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except ComfyUIError as e:
            raise ToolError(str(e)) from e

    return wrapper


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
        """
        text = Path(__file__).with_name("user-guide.md").read_text(encoding="utf-8")
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
        return {"workflows": mgr.list_workflows_gated()}

    @srv.tool()
    @mcp_tool_guard
    async def comfyui_describe_workflow(name: str, instance: str = "") -> dict:
        """解析工作流 + 实例健康检查 + 路由推荐 + 内存执行统计。

        返回 inputs/outputs/nodes 及三块：
        - health: executable（未发现阻塞项，必要非充分）/ nodes_missing（自定义节点未安装）/
          models_missing（COMBO 字面量不在该实例选项列表，如模型文件缺失）；
          实例不可达/登录失败时降级为 {checked: false, reason}，本地解析照常返回
        - routing（P5.13 路由推荐）: recommended_instance = 符合要求（config 规则∩可达）
          且排队最少（加权最低分，平局→default_instance）；candidates 列出每个实例的
          supported/excluded_reason/queued/running/health/score；全不可达时为 null + reason。
          **upload_file / submit_task 的 instance 参数必填——用这里的 recommended_instance**
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
                                               available_sample, available_count}...]}
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
            mgr.config.allowed_workflows, name)
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
                                  timeout_s: float = 3600.0) -> dict:
        """提交工作流执行（唯一执行入口），立即返回 task_id。

        instance 必填：用 comfyui_describe_workflow 返回的 routing.recommended_instance
        （符合要求 ∩ 排队最少）；点名实例不匹配其 config 规则（workflow_rules）时
        立即报错（硬拒，不排队后炸）。

        用 comfyui_task_status 轮询进度（建议间隔 10–30s；completed 后其返回中
        含 outputs 本地文件路径与 text_outputs），用 comfyui_cancel_task 取消
        （排队中=删远端队列，执行中=/interrupt）。

        Args:
            instance: 实例名（必填，不能为空；取 describe 的 routing.recommended_instance）
            workflow_name: 工作流名（与 prompt_json 二选一）
            prompt_json: 内联 API 格式工作流 JSON 字符串（内联无名字，不受实例规则限制）
            params: 参数注入，如 {"INPUT_POSITIVE_TEXT": "...", "seed": 42}；
                媒体参数为文件名（先 comfyui_upload_file 上传取 name，
                如 {"INPUT_IMAGE_FILE": "xxx_ref.png"}，须同一实例）
            timeout_s: 总超时秒（默认 3600，含排队等待；超时后按状态停止并记 FAILED）
        """
        wf, wf_name = _resolve_workflow(mgr, workflow_name, prompt_json)
        task_id = await mgr.submit_workflow(
            instance=instance, workflow=wf, params=params,
            workflow_name=wf_name, timeout_s=timeout_s,
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
    async def comfyui_upload_file(instance: str,
                                  file_path: str = "",
                                  file_b64: str = "",
                                  filename: str = "",
                                  file_type: str = "input") -> dict:
        """上传文件到 ComfyUI（图片/音频/视频等任意类型；返回的 name 供工作流节点引用，
        如 LoadImage / LoadAudio / VHS_LoadVideo）。

        instance 必填：必须与后续 submit_task 的 instance 一致（媒体文件实例局部，
        取同一份 describe 的 routing.recommended_instance）。

        与媒体输入工作流配套（P5.10 统一约定）：先上传取返回的 name，再以 params
        注入对应 INPUT_*_FILE（如 INPUT_IMAGE_FILE），上传与执行须同一实例；
        file_b64 分支仅远程/跨机器客户端使用（本服务机上的素材走 file_path）。

        Args:
            instance: 实例名（必填，与 submit_task 同一实例；取 describe 的 routing.recommended_instance）
            file_path: 本地文件路径（与 file_b64 二选一；后缀原样保留，最省心）
            file_b64: base64 文件数据（支持裸 base64 与 data-URI 如 data:audio/wav;base64,...；图片/音频/视频扩展名均可识别）
            filename: 仅 file_b64 分支用，只取其后缀（如 clip.mp4 / .aac）；最终落盘名为随机名+该后缀，以返回的 name 为准；音频/视频 base64 建议传
            file_type: 目标文件夹 input / output / temp（ComfyUI 端目录）
        """
        target = file_path
        tmp = None
        if not target and file_b64:
            try:
                data, mime = _decode_b64_payload(file_b64)
            except (binascii.Error, ValueError) as e:
                return {"ok": False, "error": f"base64 解码失败：{e}"}
            suffix = _resolve_b64_suffix(filename, file_b64, mime)
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.write(data)
            tmp.close()
            target = tmp.name
            logger.info("[upload] b64 分支：suffix=%s mime=%s size=%d",
                        suffix, mime, len(data))
        try:
            return await mgr.upload_image(instance, target,
                                          image_type=file_type)
        finally:
            if tmp is not None:
                try:
                    import os
                    os.unlink(tmp.name)
                except OSError:
                    pass

    return srv
