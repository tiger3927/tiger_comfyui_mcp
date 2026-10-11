"""模拟支付页 + 确认到账（Task-WWW.md §6）。

GET /pay/{order_no} 匿名可达（扫码落地页数据）；POST /pay/{order_no}/confirm
pending→paid，recharge_auto_credit 再 →credited 并写 ledger(recharge)。
grant_credits 按 (recharge, order, order_no) 唯一约束天然幂等，重复确认不重复入账。
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from portal.accounts import grant_credits
from portal.db import utcnow
from portal.errors import BadRequest, NotFound

router = APIRouter(tags=["pay"])


async def _credit_order(db, row) -> None:
    """paid/credited 入账：写 recharge 流水 + 更新订单状态（幂等）。"""
    await grant_credits(db, user_id=row["user_id"], delta=row["credits"],
                        kind="recharge", ref_kind="order", ref_id=row["order_no"],
                        note=f"模拟充值 {row['amount_rmb']} 元")
    await db.execute(
        "UPDATE recharge_orders SET status='credited', credited_at=? WHERE id=?",
        (utcnow(), row["id"]))


@router.get("/pay/{order_no}")
async def pay_page(order_no: str, request: Request):
    db = request.app.state.db
    row = await db.fetch_one(
        "SELECT order_no, amount_rmb, credits, status, created_at"
        " FROM recharge_orders WHERE order_no=?", (order_no,))
    if row is None:
        raise NotFound("订单不存在")
    return {"order_no": row["order_no"], "amount_rmb": row["amount_rmb"],
            "credits": row["credits"], "status": row["status"]}


@router.post("/pay/{order_no}/confirm")
async def pay_confirm(order_no: str, request: Request):
    db = request.app.state.db
    settings = request.app.state.portal_settings
    row = await db.fetch_one(
        "SELECT id, order_no, user_id, amount_rmb, credits, status FROM recharge_orders"
        " WHERE order_no=?", (order_no,))
    if row is None:
        raise NotFound("订单不存在")
    if row["status"] == "credited":
        return {"order_no": order_no, "status": "credited"}  # 幂等
    if row["status"] == "cancelled":
        raise BadRequest("订单已作废（超时未付），请重新下单")
    if row["status"] == "pending":
        await db.execute(
            "UPDATE recharge_orders SET status='paid', paid_at=? WHERE id=?",
            (utcnow(), row["id"]))
    if settings.recharge_auto_credit:
        await _credit_order(db, row)
        return {"order_no": order_no, "status": "credited"}
    return {"order_no": order_no, "status": "paid"}
