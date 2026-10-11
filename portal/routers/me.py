"""个人中心：/me 概览 + 改密码 + 流水 + 充值记录（Task-WWW.md §6）。"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from portal.accounts import set_password
from portal.errors import BadRequest
from portal.security import get_current_user, verify_password

router = APIRouter(tags=["me"])

_COST = "status IN ('completed','cancelled')"


@router.get("/me")
async def get_me(request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    uid = user["id"]
    used = await db.scalar(
        f"SELECT COALESCE(SUM(billable_credits),0) FROM task_records"
        f" WHERE user_id=? AND {_COST}", (uid,), default=0)
    token_count = await db.scalar(
        "SELECT COUNT(*) FROM user_tokens WHERE user_id=?", (uid,), default=0)
    now = time.time()
    day = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(now))
    month = time.strftime("%Y-%m-01T00:00:00Z", time.gmtime(now))
    today = await db.scalar(
        f"SELECT COALESCE(SUM(billable_credits),0) FROM task_records"
        f" WHERE user_id=? AND {_COST} AND finished_at>=?", (uid, day), default=0)
    m = await db.scalar(
        f"SELECT COALESCE(SUM(billable_credits),0) FROM task_records"
        f" WHERE user_id=? AND {_COST} AND finished_at>=?", (uid, month), default=0)
    return {"id": uid, "username": user["username"], "role": user["role"],
            "balance": user["balance"], "used": used, "token_count": token_count,
            "today_credits": today, "month_credits": m}


class ChangePwd(BaseModel):
    old_password: str
    new_password: str


@router.post("/me/password")
async def change_password(request: Request, body: ChangePwd,
                          user: dict = Depends(get_current_user)):
    db = request.app.state.db
    row = await db.fetch_one("SELECT pass_hash FROM users WHERE id=?", (user["id"],))
    if not verify_password(body.old_password, row["pass_hash"]):
        raise BadRequest("旧密码错误")
    await set_password(db, user["id"], body.new_password)
    return {"ok": True}


@router.get("/me/ledger")
async def my_ledger(request: Request, page: int = 1, size: int = 20,
                    user: dict = Depends(get_current_user)):
    db = request.app.state.db
    page = max(1, page)
    size = min(200, max(1, size))
    total = await db.scalar(
        "SELECT COUNT(*) FROM credit_ledger WHERE user_id=?", (user["id"],), default=0)
    rows = await db.fetch_all(
        "SELECT kind, ref_kind, ref_id, delta, balance_after, note, created_at"
        " FROM credit_ledger WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
        (user["id"], size, (page - 1) * size))
    return {"total": total, "page": page, "size": size,
            "items": [dict(r) for r in rows]}


@router.get("/me/recharges")
async def my_recharges(request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    rows = await db.fetch_all(
        "SELECT order_no, amount_rmb, credits, status, qr_url, paid_at, credited_at,"
        " created_at FROM recharge_orders WHERE user_id=? ORDER BY id DESC",
        (user["id"],))
    return {"recharges": [dict(r) for r in rows]}
