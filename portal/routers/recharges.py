"""充值下单：/recharges（模拟支付，Task-WWW.md §6）。"""
from __future__ import annotations

import secrets
import time

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from portal.errors import BadRequest, NotFound
from portal.db import utcnow
from portal.security import get_current_user

router = APIRouter(tags=["recharges"])


class RechargeIn(BaseModel):
    amount: float  # 人民币元（如 100）


def _credits_for(amount: float, rmb_per_credit: float) -> int:
    """100 元 = 10000 积分（rmb_per_credit=0.01）；用 round 防浮点尾巴。"""
    return int(round(amount / rmb_per_credit))


def _qr_url(settings, order_no: str) -> str:
    base = (settings.public_base_url or "").rstrip("/")
    return f"{base}/portal/pay/{order_no}" if base else f"/portal/pay/{order_no}"


@router.post("/recharges")
async def create_recharge(request: Request, body: RechargeIn,
                          user: dict = Depends(get_current_user)):
    db = request.app.state.db
    settings = request.app.state.portal_settings
    if body.amount < settings.recharge_min or body.amount > settings.recharge_max:
        raise BadRequest(
            f"充值金额需在 {settings.recharge_min}-{settings.recharge_max} 元之间")
    credits = _credits_for(body.amount, settings.rmb_per_credit)
    order_no = f"RC{int(time.time())}{secrets.token_hex(4).upper()}"
    qr_url = _qr_url(settings, order_no)
    await db.execute(
        "INSERT INTO recharge_orders(order_no, user_id, amount_rmb, credits, status,"
        " qr_url, created_at) VALUES(?,?,?,?, 'pending', ?, ?)",
        (order_no, user["id"], body.amount, credits, qr_url, utcnow()))
    return {"order_no": order_no, "amount_rmb": body.amount, "credits": credits,
            "qr_url": qr_url, "status": "pending"}


@router.get("/recharges/{order_no}")
async def get_recharge(request: Request, order_no: str,
                       user: dict = Depends(get_current_user)):
    db = request.app.state.db
    row = await db.fetch_one(
        "SELECT order_no, amount_rmb, credits, status, qr_url, paid_at, credited_at,"
        " created_at FROM recharge_orders WHERE order_no=? AND user_id=?",
        (order_no, user["id"]))
    if row is None:
        raise NotFound("订单不存在")
    return dict(row)
