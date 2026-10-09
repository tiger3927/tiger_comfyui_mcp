"""tiger_comfyui_mcp 入口。

单 uvicorn 进程单端口（默认 0.0.0.0:18800）双入口：
  /mcp/        MCP Streamable HTTP（stateless）
  /api/*       REST webapi
  /files/*     output/ 产物下载

启动：
  D:\\miniconda3\\python.exe main.py            # 用 config.json 的 server.host/port
  D:\\miniconda3\\python.exe main.py --port 18503   # 命令行覆盖端口
"""
from __future__ import annotations

import asyncio
import logging
import logging.handlers
import sys
from contextlib import asynccontextmanager
from pathlib import Path

if sys.platform == "win32":
    # aiohttp WebSocket 在 Windows 上需要 selector 事件循环
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn
from fastapi import FastAPI, Request
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from core.cleanup import start_cleanup_loop
from core.manager import get_manager
from server.mcp_tools import build_mcp_server
from server.rest_api import build_router, files_router

PROJECT_ROOT = Path(__file__).resolve().parent

# 写类（执行）MCP 工具名；query_token 调用这些工具将被拒绝
WRITE_TOOLS = frozenset({
    "comfyui_submit_task", "comfyui_cancel_task", "comfyui_upload_file",
})
# REST 写类路径前缀
WRITE_PREFIXES = ("/api/tasks", "/api/upload")


# ----------------------------------------------------------------------
# ASGI lifespan 驱动（starlette 1.x 删除了 lifespan_context 工具）
# ----------------------------------------------------------------------
def drive_lifespan(app):
    import asyncio

    @asynccontextmanager
    async def _drive():
        startup_done = asyncio.Event()
        shutdown_done = asyncio.Event()
        queue: asyncio.Queue = asyncio.Queue()

        async def receive():
            return await queue.get()

        async def send(message):
            t = message["type"]
            if t == "lifespan.startup.complete":
                startup_done.set()
            elif t == "lifespan.startup.failed":
                raise RuntimeError("MCP 子应用 lifespan 启动失败")
            elif t == "lifespan.shutdown.complete":
                shutdown_done.set()

        task = asyncio.create_task(app({"type": "lifespan"}, receive, send))
        queue.put_nowait({"type": "lifespan.startup"})
        await startup_done.wait()
        try:
            yield
        finally:
            queue.put_nowait({"type": "lifespan.shutdown"})
            await shutdown_done.wait()
            await task

    return _drive()


async def _startup_reconcile(manager) -> None:
    """启动对账（P5.11，纯观察）：各实例远端队列是否有活动任务。

    服务重启丢内存任务表、client_id 每进程随机 uuid4 无法回溯关联——仅 warning
    提示"有 N 个不可追踪的远端任务"，零行为变化。
    """
    log = logging.getLogger("main")
    try:
        for st in await manager.status_all():
            if st.get("connected") and (st.get("queue_running") or st.get("queue_pending")):
                log.warning("[对账] %s 远端有 %d 执行中 / %d 排队任务"
                            "（非本进程提交，不可追踪）",
                            st.get("name"), st.get("queue_running", 0),
                            st.get("queue_pending", 0))
    except Exception as e:
        log.debug("[对账] 启动对账失败：%s", e)


def setup_logging() -> None:
    log_dir = PROJECT_ROOT / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "server.log", maxBytes=5 * 1024 * 1024,
        backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console)
    # mcp SDK 每请求/会话打 INFO，日志风暴（vnpy 同款处理）
    logging.getLogger("mcp").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


def build_app(config_path: Path | None = None) -> FastAPI:
    setup_logging()
    log = logging.getLogger("main")

    # 认证策略（D3）：两 token 均未配置 → 无认证运行（仅本机调试）
    manager = get_manager(config_path or PROJECT_ROOT / "config.json")
    command_token = manager.config.command_token
    query_token = manager.config.query_token
    auth_enabled = bool(command_token or query_token)
    if not auth_enabled:
        log.warning("未配置 command_token/query_token：服务以无认证模式运行（仅限本机调试！"
                    "远程访问务必配置强 token）")

    sub = build_mcp_server(manager)  # MCPServer 实例
    # mcp 2.x DNS rebinding 防护：默认仅放行 localhost 的 Host，非本机地址连 /mcp/ 返回 421。
    # 配置了 mcp_allowed_hosts/origins 才显式传入（支持 "host:*" 通配端口）；否则 None=SDK 默认
    scfg = manager.config.server
    ts = None
    if scfg.mcp_allowed_hosts or scfg.mcp_allowed_origins:
        ts = TransportSecuritySettings(
            allowed_hosts=list(scfg.mcp_allowed_hosts),
            allowed_origins=list(scfg.mcp_allowed_origins))
    mcp_app = sub.streamable_http_app(streamable_http_path="/", stateless_http=True,
                                     transport_security=ts)
    drive = drive_lifespan(mcp_app)  # 已返回上下文管理器，勿再调用

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with drive:
            log.info("服务启动：实例=%s 认证=%s 端口=%s:%s",
                     manager.instance_names(),
                     "on" if auth_enabled else "OFF",
                     manager.config.server.host, manager.config.server.port)
            c = manager.config
            cleanup_task = asyncio.create_task(
                start_cleanup_loop(manager.output_dir, c.output_retention_days,
                                   c.cleanup_interval_hours, manager.tasks,
                                   c.task_retention_hours, c.task_max_retained),
                name="cleanup-loop")
            log.info("清理任务启动：output 保留 %s 天 / 周期 %s 小时 / "
                     "终态任务保留 %s 小时且最近 %s 条",
                     c.output_retention_days, c.cleanup_interval_hours,
                     c.task_retention_hours, c.task_max_retained)
            asyncio.create_task(_startup_reconcile(manager), name="startup-reconcile")
            log.info("启动对账已发起（远端活动任务计数，纯观察）")
            try:
                yield
            finally:
                cleanup_task.cancel()
                try:
                    await cleanup_task
                except (asyncio.CancelledError, Exception):
                    pass

    app = FastAPI(title="tiger-comfyui-mcp", lifespan=lifespan)

    class AuthMiddleware(BaseHTTPMiddleware):
        """两级 Bearer：command_token 全权限；query_token 只读（写类工具/路径拒绝）。"""

        async def dispatch(self, request: Request, call_next):
            # P5.20：/files/ 匿名下载（文件名含随机任务前缀，实际不可猜测）；
            # 外部调用者经 task_status 的 outputs_urls 直链取产物，无需 Bearer
            if not request.url.path.startswith(("/mcp", "/api")):
                return await call_next(request)
            if auth_enabled:
                auth = request.headers.get("Authorization", "")
                token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
                level = None
                if token and command_token and token == command_token:
                    level = "command"
                elif token and query_token and token == query_token:
                    level = "query"
                if level is None:
                    if request.url.path.startswith("/mcp"):
                        return JSONResponse(
                            {"jsonrpc": "2.0", "id": -1,
                             "error": {"code": -32001, "message": "unauthorized"}},
                            status_code=401)
                    return JSONResponse({"error": "unauthorized"}, status_code=401)
                if level == "query":
                    if request.url.path.startswith("/mcp"):
                        # 读 body 判工具名（stateless：一次请求一条消息）
                        try:
                            body = await request.json()
                            method = body.get("method", "")
                            if method == "tools/call":
                                tool = (body.get("params") or {}).get("name", "")
                                if tool in WRITE_TOOLS:
                                    return JSONResponse(
                                        {"jsonrpc": "2.0", "id": body.get("id", -1),
                                         "error": {"code": -32002,
                                                   "message": f"query token 无权调用执行类工具 {tool}"}},
                                        status_code=403)
                        except Exception:
                            pass  # 非 JSON 或解析失败放行（协议层会处理）
                    elif request.url.path.startswith(WRITE_PREFIXES):
                        return JSONResponse({"error": "forbidden: query token 只读"},
                                            status_code=403)
            return await call_next(request)

    app.add_middleware(AuthMiddleware)
    app.include_router(build_router(manager))
    app.include_router(files_router(manager))

    @app.get("/")
    async def root():
        return {"service": "tiger-comfyui-mcp",
                "endpoints": ["/mcp/", "/api/*", "/files/*"]}

    app.mount("/mcp", mcp_app, name="mcp")
    return app


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="tiger_comfyui_mcp 服务入口")
    parser.add_argument("--port", type=int, default=None,
                        help="监听端口（覆盖 config.json 的 server.port）")
    parser.add_argument("--host", type=str, default=None,
                        help="监听地址（覆盖 config.json 的 server.host）")
    args = parser.parse_args()

    app = build_app()
    cfg = get_manager(PROJECT_ROOT / "config.json").config.server
    uvicorn.run(app, host=args.host or cfg.host, port=args.port or cfg.port,
                log_level="warning")
