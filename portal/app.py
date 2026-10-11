"""portal/app.py：组合门户 FastAPI 子 app（Task-WWW.md §10、§6、§5.2）。

设计取舍：
- build_portal_app(settings, task_provider) 只搭路由 + 异常处理，**不自动开库**；
- start(app) / stop(app) 显式管理 DB 与后台循环（幂等）。
  原因：主进程里门户是 `app.mount("/portal/api", portal_app)` 挂载的子 app，
  旧版 Starlette 挂载子 app 的 lifespan 不保证随父启动而跑（starlette#1183）；
  显式 start/stop 由 main.py 的 _startup/_shutdown 调用，测试夹具同样显式调用，
  行为最可预测，且 start/stop 幂等可防重入。

红线（§2.1）：只 import portal.* + fastapi/starlette/asyncio，零 import core/server；
task_provider 是 main.py 注入的无参 callable（返回 [dict]，即 TaskManager.list_full）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from portal import billing, sync
from portal.config import PortalSettings
from portal.db import PortalDB
from portal.errors import PortalError
from portal.routers import admin, auth, me, pay, recharges, tasks, tokens

logger = logging.getLogger("portal.app")


def build_portal_app(settings: PortalSettings,
                     task_provider: Callable[[], list[dict]]) -> FastAPI:
    app = FastAPI(title="tiger-portal")
    app.state.portal_settings = settings
    app.state.task_provider = task_provider
    app.state.db = None
    app.state.sync_task = None
    app.state.recharge_task = None

    @app.exception_handler(PortalError)
    async def _portal_error_handler(request: Request, exc: PortalError):
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict())

    for r in (auth.router, me.router, tokens.router, tasks.router,
              recharges.router, pay.router, admin.router):
        app.include_router(r)

    async def precheck(workflow_name: str, params: dict, user_token,
                       task_id: str) -> None:
        """precheck 注入点（main.py: manager.precheck = app.precheck）。
        内部走 billing.precheck_and_freeze（匿名/停用/余额/在途上限各拒因）。"""
        db: PortalDB = app.state.db
        if db is None:
            raise PortalError("portal 未启动", "PortalNotReady", 503)
        await billing.precheck_and_freeze(db, settings, workflow_name, params,
                                          user_token, task_id)

    app.precheck = precheck
    return app


async def start(app: FastAPI) -> None:
    """开 DB → 启动对账 → 起 sync 循环 + 充值超时循环。幂等（已开则直接返回）。"""
    if app.state.db is not None:
        return
    settings: PortalSettings = app.state.portal_settings
    db = await PortalDB.open(settings)
    app.state.db = db
    try:
        await sync.startup_reconcile(db, settings, app.state.task_provider)
    except Exception:
        logger.exception("[portal] 启动对账异常（已吞掉，不阻断启动）")
    app.state.sync_task = asyncio.create_task(
        sync.sync_loop(db, settings, app.state.task_provider), name="portal-sync")
    app.state.recharge_task = asyncio.create_task(
        sync.recharge_timeout_loop(db, settings), name="portal-recharge-timeout")
    logger.info("[portal] 就绪：db=%s 匿名=%s", settings.db_path,
                await db.get_setting("allow_anonymous", "1"))


async def stop(app: FastAPI) -> None:
    """停后台循环 + 关 DB。幂等。"""
    for attr in ("sync_task", "recharge_task"):
        t = getattr(app.state, attr, None)
        if t is not None:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
            setattr(app.state, attr, None)
    if app.state.db is not None:
        await app.state.db.close()
        app.state.db = None
        logger.info("[portal] 已关闭")
