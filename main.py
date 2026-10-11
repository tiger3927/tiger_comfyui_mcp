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
from portal.billing import resolve_user_token
from portal.errors import InvalidToken
from server.mcp_tools import build_mcp_server
from server.rest_api import build_router, files_router

PROJECT_ROOT = Path(__file__).resolve().parent

# MCP 无 key 可访问的握手/发现方法（Task-WWW §5.3：不放行则无 key 客户端连 guide 都调不到）
MCP_PUBLIC_METHODS = frozenset({
    "initialize", "notifications/initialized", "ping", "tools/list",
})
# MCP 无 key 可调的只读工具（不含用户数据 / 不计费 / 无副作用）。
# request_upload_ticket 仅写内存态短命票据（无持久副作用、不挂身份），
# 是无 key agent 走 REST 上传的唯一桥梁，故纳入豁免。
MCP_PUBLIC_TOOLS = frozenset({
    "comfyui_user_guide", "comfyui_list_workflows",
    "comfyui_status", "comfyui_describe_workflow",
    "comfyui_request_upload_ticket",
})


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

    manager = get_manager(config_path or PROJECT_ROOT / "config.json")

    # ── 门户（Task-WWW.md）：config 有 "portal" 段才启用 ──
    portal_app: FastAPI | None = None
    try:
        import json as _json
        _cfg_path = config_path or PROJECT_ROOT / "config.json"
        _raw_cfg = (_json.loads(Path(_cfg_path).read_text(encoding="utf-8"))
                    if Path(_cfg_path).exists() else {})
        _portal_raw = _raw_cfg.get("portal")
        if isinstance(_portal_raw, dict):
            from portal.config import PortalSettings
            from portal.app import build_portal_app
            _psettings = PortalSettings.from_dict(
                _portal_raw, public_base_url=manager.config.server.public_base_url)
            portal_app = build_portal_app(_psettings, manager.tasks.list_full)
            manager.precheck = portal_app.precheck
            log.info("[portal] 已启用：db=%s", _psettings.db_path)
        else:
            log.info("[portal] config 无 portal 段，门户未启用")
    except Exception:
        log.exception("[portal] 初始化失败（降级：门户不可用，MCP/REST 照常）")
        portal_app = None

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
                     "on" if portal_app is not None else "OFF",
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
            if portal_app is not None:
                try:
                    from portal.app import start as _portal_start
                    await _portal_start(portal_app)
                except Exception:
                    log.exception("[portal] 启动失败（降级：门户暂不可用）")
            try:
                yield
            finally:
                if portal_app is not None:
                    try:
                        from portal.app import stop as _portal_stop
                        await _portal_stop(portal_app)
                    except Exception:
                        log.exception("[portal] 关闭失败（忽略）")
                cleanup_task.cancel()
                try:
                    await cleanup_task
                except (asyncio.CancelledError, Exception):
                    pass

    app = FastAPI(title="tiger-comfyui-mcp", lifespan=lifespan)

    class AuthMiddleware(BaseHTTPMiddleware):
        """API Key 鉴权（Task-WWW §5.3）：/mcp、/api 走 resolve_user_token（Bearer pt_xxx）；
        MCP 只读工具 + 握手方法豁免（无 key 可调）；/portal/api、/files 不拦。
        门户未启用（无 db）→ 不强制鉴权（仅本机调试）。"""

        @staticmethod
        def _unauthorized(request: Request):
            if request.url.path.startswith("/mcp"):
                return JSONResponse(
                    {"jsonrpc": "2.0", "id": -1,
                     "error": {"code": -32001, "message": "unauthorized"}},
                    status_code=401)
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        async def dispatch(self, request: Request, call_next):
            if not request.url.path.startswith(("/mcp", "/api")):
                return await call_next(request)
            db = portal_app.state.db if portal_app is not None else None
            if db is None:
                # 门户未启用（无 API Key 体系）→ 不强制鉴权（仅本机调试）
                return await call_next(request)
            if request.url.path.startswith("/mcp"):
                try:
                    body = await request.json()  # Starlette 缓存 body，下游仍可再读
                except Exception:
                    body = {}
                method = body.get("method", "")
                if method in MCP_PUBLIC_METHODS:
                    return await call_next(request)  # 豁免：握手/发现
                if method == "tools/call" and \
                        (body.get("params") or {}).get("name", "") in MCP_PUBLIC_TOOLS:
                    return await call_next(request)  # 豁免：只读工具
            if request.url.path == "/api/upload" and \
                    (request.query_params.get("ticket") or "").strip():
                # 票据上传通道：免 Bearer，端点内核验票据（短时效单次、绑定实例）。
                # 无效票据在端点归 403，不在此处放行非票据请求。
                return await call_next(request)
            auth = request.headers.get("Authorization", "")
            token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
            if not token:
                return self._unauthorized(request)
            try:
                user_row, _ = await resolve_user_token(db, token)
            except InvalidToken:
                return self._unauthorized(request)
            request.state.user_id = user_row["uid"]
            return await call_next(request)

    app.add_middleware(AuthMiddleware)
    app.include_router(build_router(manager))
    app.include_router(files_router(manager))

    @app.get("/")
    async def root():
        return {"service": "tiger-comfyui-mcp",
                "endpoints": ["/mcp/", "/api/*", "/files/*"]}

    app.mount("/mcp", mcp_app, name="mcp")

    # 门户挂载：API 在前（/portal/api 优先匹配），SPA / catch-all 在后
    if portal_app is not None:
        app.mount("/portal/api", portal_app)
        _dist = PROJECT_ROOT / "www" / "dist"
        if _dist.is_dir():
            from starlette.staticfiles import StaticFiles
            app.mount("/portal", StaticFiles(directory=str(_dist), html=True),
                      name="portal-spa")
        else:
            @app.get("/portal/{full_path:path}")
            async def _portal_placeholder(full_path: str):
                return JSONResponse(
                    {"error": {"code": "FrontendNotBuilt",
                               "message": "门户前端未构建（www/dist 缺失）"}},
                    status_code=404)
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
