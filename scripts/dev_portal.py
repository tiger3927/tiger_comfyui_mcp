"""本机纯门户后端（M3 前端联调用，无 ComfyUI / 无 core/manager）。

为什么需要它：本机无 GPU、无 ComfyUI，跑不起 main.py（要连 ComfyUI manager）。
但门户功能（注册/登录/token/充值/账户/流水）完全不依赖 ComfyUI——只依赖 portal.db。
本脚本只 import portal.*，task_provider 恒返回 []（无真实任务，任务列表为空），
从而让前端 7 页的端到端流程在纯本地跑通。真实任务执行/计费结算留服务器真机（M2）。

端口与生产一致 18503，vite dev 的 proxy 直接指向它（见 www/vite.config.js）。

用法（base conda 环境）：
    python scripts/dev_portal.py
    # 另开终端：
    npm --prefix www run dev        # 浏览器开 http://127.0.0.1:5173/portal/
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from portal.app import build_portal_app, start, stop
from portal.config import PortalSettings

HOST = "127.0.0.1"
PORT = 18503
DEV_JWT_SECRET = "dev-portal-secret-not-for-prod-0123456789"


def build_settings() -> PortalSettings:
    """读 config.json 的 portal 段（若存在）；否则用默认值。
    dev 强制独立库 data/portal_dev.db（不碰生产 data/portal.db）+ 固定 JWT 密钥。"""
    cfg: dict = {}
    cfg_file = ROOT / "config.json"
    if cfg_file.exists():
        cfg = json.loads(cfg_file.read_text(encoding="utf-8")).get("portal") or {}
    settings = PortalSettings.from_dict(cfg, public_base_url="")
    settings.db_path = str(ROOT / "data" / "portal_dev.db")
    if not settings.has_jwt_secret:
        settings.jwt_secret = os.environ.get("PORTAL_JWT_SECRET") or DEV_JWT_SECRET
    return settings


def build_app() -> FastAPI:
    settings = build_settings()
    # task_provider 恒 [] —— 无真实任务，但 sync 循环/对账照常空转。
    portal_app = build_portal_app(settings, task_provider=lambda: [])

    app = FastAPI(title="tiger-portal-dev")
    app.mount("/portal/api", portal_app)

    # build 产物兜底：若 www/dist 存在（npm run build 过），静态挂 /portal/。
    # 开发期前端由 vite(5173) 提供，这里仅给"直接访问 18503/portal/"的场景兜底。
    dist = ROOT / "www" / "dist"
    if dist.exists():
        app.mount("/portal", StaticFiles(directory=str(dist), html=True), name="portal-static")

    @app.on_event("startup")
    async def _up():
        await start(portal_app)

    @app.on_event("shutdown")
    async def _down():
        await stop(portal_app)

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    uvicorn.run(build_app(), host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
