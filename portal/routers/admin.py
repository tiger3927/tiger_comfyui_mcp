"""管理端 /admin/*（全量权限，require_admin；全部写操作记 admin_audit，
Task-WWW.md §6、§8）。"""
from __future__ import annotations

import secrets
import time
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from portal.accounts import grant_credits
from portal.db import utcnow
from portal.errors import BadRequest, NotFound
from portal.security import require_admin

from portal.routers.pay import _credit_order

router = APIRouter(tags=["admin"])


async def _audit(db, admin_id: int, action: str, target: str, detail: str = "") -> None:
    await db.execute(
        "INSERT INTO admin_audit(admin_id, action, target, detail, created_at)"
        " VALUES(?,?,?,?,?)", (admin_id, action, target, detail, utcnow()))


class AdjustIn(BaseModel):
    delta: int
    note: str = ""


class DisableIn(BaseModel):
    disabled: int  # 0/1


class RuleIn(BaseModel):
    pattern: str
    media: str
    price_per_mp: float = 0.0
    price_per_char: float = 0.0
    flat_price: int = 0
    fps: int = 0
    width_param: Optional[str] = None
    height_param: Optional[str] = None
    seconds_param: Optional[str] = None
    char_param: Optional[str] = None
    default_width: Optional[int] = None
    default_height: Optional[int] = None
    active: int = 1
    remark: str = ""


# ------------------------------------------------------------------ 用户
@router.get("/admin/users")
async def list_users(request: Request, q: str = Query(""),
                     user: dict = Depends(require_admin)):
    db = request.app.state.db
    sql = ("SELECT u.id, u.username, u.role, u.balance, u.active_count, u.disabled,"
           " u.created_at,"
           " (SELECT COALESCE(SUM(used),0) FROM user_tokens WHERE user_id=u.id) AS used,"
           " (SELECT COUNT(*) FROM task_records WHERE user_id=u.id) AS task_count"
           " FROM users u")
    args = []
    if q:
        sql += " WHERE u.username LIKE ?"
        args.append(f"%{q}%")
    sql += " ORDER BY u.id DESC"
    rows = await db.fetch_all(sql, tuple(args))
    return {"users": [dict(r) for r in rows]}


@router.get("/admin/users/{uid}")
async def user_detail(request: Request, uid: int,
                      user: dict = Depends(require_admin)):
    db = request.app.state.db
    u = await db.fetch_one(
        "SELECT id, username, role, balance, active_count, disabled, created_at"
        " FROM users WHERE id=?", (uid,))
    if u is None:
        raise NotFound("用户不存在")
    tokens = await db.fetch_all(
        "SELECT id, name, token_prefix, credit_limit, used, expires_at, disabled"
        " FROM user_tokens WHERE user_id=?", (uid,))
    ledger = await db.fetch_all(
        "SELECT kind, ref_kind, ref_id, delta, balance_after, note, created_at"
        " FROM credit_ledger WHERE user_id=? ORDER BY id DESC LIMIT 100", (uid,))
    tasks = await db.fetch_all(
        "SELECT mcp_task_id, workflow_name, status, billable_credits, submitted_at,"
        " finished_at FROM task_records WHERE user_id=? ORDER BY id DESC LIMIT 100",
        (uid,))
    return {"user": dict(u), "tokens": [dict(t) for t in tokens],
            "ledger": [dict(l) for l in ledger], "tasks": [dict(t) for t in tasks]}


@router.post("/admin/users/{uid}/adjust")
async def adjust_balance(request: Request, uid: int, body: AdjustIn,
                         user: dict = Depends(require_admin)):
    db = request.app.state.db
    if body.delta == 0:
        raise BadRequest("delta 不能为 0")
    if (await db.scalar("SELECT id FROM users WHERE id=?", (uid,))) is None:
        raise NotFound("用户不存在")
    ref = f"admin:{user['id']}:{uid}:{int(time.time())}:{secrets.token_hex(4)}"
    after = await grant_credits(db, user_id=uid, delta=body.delta, kind="adjust",
                                ref_kind="admin", ref_id=ref,
                                note=body.note or "管理员调整")
    await _audit(db, user["id"], "adjust_balance", str(uid),
                 f"delta={body.delta} note={body.note} after={after}")
    return {"ok": True, "balance": after}


@router.patch("/admin/users/{uid}")
async def set_user(request: Request, uid: int, body: DisableIn,
                   user: dict = Depends(require_admin)):
    db = request.app.state.db
    if (await db.scalar("SELECT id FROM users WHERE id=?", (uid,))) is None:
        raise NotFound("用户不存在")
    await db.execute("UPDATE users SET disabled=? WHERE id=?",
                     (1 if body.disabled else 0, uid))
    await _audit(db, user["id"],
                 "disable_user" if body.disabled else "enable_user", str(uid), "")
    return {"ok": True}


# ------------------------------------------------------------------ token
@router.get("/admin/tokens")
async def list_tokens(request: Request, user: dict = Depends(require_admin)):
    db = request.app.state.db
    rows = await db.fetch_all(
        "SELECT t.id, t.user_id, u.username, t.name, t.token_prefix, t.credit_limit,"
        " t.used, t.disabled, t.expires_at FROM user_tokens t"
        " JOIN users u ON u.id=t.user_id ORDER BY t.id DESC")
    return {"tokens": [dict(r) for r in rows]}


# ------------------------------------------------------------------ 充值单
@router.get("/admin/recharges")
async def list_recharges(request: Request, status: str = Query(""),
                         uid: int = Query(0),
                         user: dict = Depends(require_admin)):
    db = request.app.state.db
    where, args = [], []
    if status:
        where.append("o.status=?")
        args.append(status)
    if uid:
        where.append("o.user_id=?")
        args.append(uid)
    w = (" WHERE " + " AND ".join(where)) if where else ""
    rows = await db.fetch_all(
        "SELECT o.id, o.order_no, o.user_id, u.username, o.amount_rmb, o.credits,"
        " o.status, o.paid_at, o.credited_at, o.created_at FROM recharge_orders o"
        " JOIN users u ON u.id=o.user_id" + w + " ORDER BY o.id DESC LIMIT 200",
        tuple(args))
    return {"recharges": [dict(r) for r in rows]}


@router.post("/admin/recharges/{order_no}/confirm")
async def admin_confirm(request: Request, order_no: str,
                        user: dict = Depends(require_admin)):
    db = request.app.state.db
    row = await db.fetch_one(
        "SELECT id, order_no, user_id, amount_rmb, credits, status FROM recharge_orders"
        " WHERE order_no=?", (order_no,))
    if row is None:
        raise NotFound("订单不存在")
    if row["status"] == "credited":
        return {"order_no": order_no, "status": "credited"}
    if row["status"] != "paid":
        raise BadRequest("仅 paid 单可确认入账")
    await _credit_order(db, row)
    await _audit(db, user["id"], "confirm_recharge", order_no,
                 f"credits={row['credits']}")
    return {"order_no": order_no, "status": "credited"}


@router.post("/admin/recharges/{order_no}/cancel")
async def admin_cancel(request: Request, order_no: str,
                       user: dict = Depends(require_admin)):
    db = request.app.state.db
    row = await db.fetch_one(
        "SELECT id, status FROM recharge_orders WHERE order_no=?", (order_no,))
    if row is None:
        raise NotFound("订单不存在")
    if row["status"] != "pending":
        raise BadRequest("仅 pending 单可作废")
    await db.execute(
        "UPDATE recharge_orders SET status='cancelled' WHERE id=?", (row["id"],))
    await _audit(db, user["id"], "cancel_recharge", order_no, "")
    return {"order_no": order_no, "status": "cancelled"}


# ------------------------------------------------------------------ 计费规则
@router.get("/admin/rules")
async def list_rules(request: Request, user: dict = Depends(require_admin)):
    db = request.app.state.db
    rows = await db.fetch_all("SELECT * FROM credit_rules ORDER BY id")
    return {"rules": [dict(r) for r in rows]}


@router.post("/admin/rules")
async def create_rule(request: Request, body: RuleIn,
                      user: dict = Depends(require_admin)):
    db = request.app.state.db
    cur = await db.execute(
        "INSERT INTO credit_rules(pattern, media, price_per_mp, price_per_char,"
        " flat_price, fps, width_param, height_param, seconds_param, char_param,"
        " default_width, default_height, active, remark, updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (body.pattern, body.media, body.price_per_mp, body.price_per_char,
         body.flat_price, body.fps, body.width_param, body.height_param,
         body.seconds_param, body.char_param, body.default_width,
         body.default_height, body.active, body.remark, utcnow()))
    await _audit(db, user["id"], "edit_rule", body.pattern,
                 f"create id={cur.lastrowid}")
    return {"ok": True, "id": cur.lastrowid}


@router.patch("/admin/rules/{rid}")
async def update_rule(request: Request, rid: int, body: RuleIn,
                      user: dict = Depends(require_admin)):
    db = request.app.state.db
    if (await db.scalar("SELECT id FROM credit_rules WHERE id=?", (rid,))) is None:
        raise NotFound("规则不存在")
    await db.execute(
        "UPDATE credit_rules SET pattern=?, media=?, price_per_mp=?, price_per_char=?,"
        " flat_price=?, fps=?, width_param=?, height_param=?, seconds_param=?,"
        " char_param=?, default_width=?, default_height=?, active=?, remark=?,"
        " updated_at=? WHERE id=?",
        (body.pattern, body.media, body.price_per_mp, body.price_per_char,
         body.flat_price, body.fps, body.width_param, body.height_param,
         body.seconds_param, body.char_param, body.default_width,
         body.default_height, body.active, body.remark, utcnow(), rid))
    await _audit(db, user["id"], "edit_rule", str(rid), "update")
    return {"ok": True}


# ------------------------------------------------------------------ 全部任务
@router.get("/admin/tasks")
async def list_tasks(request: Request, anonymous: bool = False,
                     uid: int = Query(0), status: str = Query(""),
                     user: dict = Depends(require_admin)):
    db = request.app.state.db
    where, args = [], []
    if anonymous:
        where.append("user_id IS NULL")
    elif uid:
        where.append("user_id=?")
        args.append(uid)
    if status:
        where.append("status=?")
        args.append(status)
    w = (" WHERE " + " AND ".join(where)) if where else ""
    rows = await db.fetch_all(
        "SELECT mcp_task_id, user_id, workflow_name, instance, status,"
        " billable_credits, submitted_at, finished_at FROM task_records" + w
        + " ORDER BY id DESC LIMIT 200", tuple(args))
    return {"tasks": [dict(r) for r in rows]}


# ------------------------------------------------------------------ 审计
@router.get("/admin/audit")
async def list_audit(request: Request, user: dict = Depends(require_admin)):
    db = request.app.state.db
    rows = await db.fetch_all(
        "SELECT id, admin_id, action, target, detail, created_at FROM admin_audit"
        " ORDER BY id DESC LIMIT 200")
    return {"audit": [dict(r) for r in rows]}


# ------------------------------------------------------------------ 系统看板（§7.2 Dashboard）
@router.get("/admin/stats")
async def stats(request: Request, days: int = Query(30, ge=1, le=365),
               user: dict = Depends(require_admin)):
    """聚合接口：KPI + 6 饼 + 6 曲线（按天分桶补零），一次返回避免 N+1。"""
    db = request.app.state.db
    COST = "status IN ('completed','cancelled')"
    now = time.time()
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - days * 86400))

    # ---------------- KPI ----------------
    user_total = await db.scalar("SELECT COUNT(*) FROM users", default=0)
    admin_count = await db.scalar("SELECT COUNT(*) FROM users WHERE role='admin'", default=0)
    total_balance = await db.scalar("SELECT COALESCE(SUM(balance),0) FROM users", default=0)
    recharge_rmb = await db.scalar(
        "SELECT COALESCE(SUM(amount_rmb),0) FROM recharge_orders WHERE status='credited'", default=0)
    recharge_credits = await db.scalar(
        "SELECT COALESCE(SUM(credits),0) FROM recharge_orders WHERE status='credited'", default=0)
    consumed = await db.scalar(
        f"SELECT COALESCE(SUM(billable_credits),0) FROM task_records WHERE {COST}", default=0)
    task_total = await db.scalar("SELECT COUNT(*) FROM task_records", default=0)
    task_completed = await db.scalar(
        "SELECT COUNT(*) FROM task_records WHERE status='completed'", default=0)
    task_failed = await db.scalar(
        "SELECT COUNT(*) FROM task_records WHERE status='failed'", default=0)
    task_active = await db.scalar(
        "SELECT COUNT(*) FROM task_records WHERE status IN ('pending','running')", default=0)
    denom = task_completed + task_failed
    kpi = {
        "user_total": user_total,
        "admin_count": admin_count,
        "user_count": user_total - admin_count,
        "total_balance": total_balance,
        "total_balance_rmb": round(total_balance * 0.01, 2),
        "recharge_rmb": recharge_rmb,
        "recharge_credits": recharge_credits,
        "consumed_credits": consumed,
        "task_total": task_total,
        "task_active": task_active,
        "task_success_rate": round(task_completed / denom, 3) if denom else 0.0,
    }

    # ---------------- 饼图 ----------------
    def _pie(rows, name_key, val_key="c"):
        return [{"name": r[name_key], "value": r[val_key]} for r in rows]

    task_status = _pie(await db.fetch_all(
        "SELECT status, COUNT(*) c FROM task_records GROUP BY status"), "status")
    workflow_top = _pie(await db.fetch_all(
        "SELECT workflow_name, COUNT(*) c FROM task_records"
        " GROUP BY workflow_name ORDER BY c DESC LIMIT 10"), "workflow_name")
    media = _pie(await db.fetch_all(
        "SELECT media, COUNT(*) c FROM credit_rules WHERE active=1 GROUP BY media"), "media")
    instance = _pie(await db.fetch_all(
        "SELECT COALESCE(NULLIF(instance,''),'未标注') inst, COUNT(*) c FROM task_records"
        " GROUP BY inst ORDER BY c DESC"), "inst")
    recharge_status = _pie(await db.fetch_all(
        "SELECT status, COUNT(*) c FROM recharge_orders GROUP BY status"), "status")
    f_recharge = await db.scalar(
        "SELECT COALESCE(SUM(delta),0) FROM credit_ledger WHERE kind='recharge'", default=0)
    f_refund = await db.scalar(
        "SELECT COALESCE(SUM(delta),0) FROM credit_ledger WHERE kind='refund'", default=0)
    f_adjust = await db.scalar(
        "SELECT COALESCE(SUM(delta),0) FROM credit_ledger WHERE kind='adjust'", default=0)
    credit_flow = [
        {"name": "充值", "value": abs(f_recharge)},
        {"name": "任务消耗", "value": abs(consumed)},
        {"name": "失败退款", "value": abs(f_refund)},
        {"name": "管理员调额", "value": abs(f_adjust)},
    ]
    credit_flow = [x for x in credit_flow if x["value"] > 0]
    pie = {
        "task_status": task_status, "workflow_top": workflow_top, "media": media,
        "instance": instance, "recharge_status": recharge_status, "credit_flow": credit_flow,
    }

    # ---------------- 曲线（按天，补零）----------------
    day_series = [time.strftime("%Y-%m-%d", time.gmtime(now - i * 86400))
                  for i in range(days - 1, -1, -1)]

    def _by_day(rows, key):
        return {r["d"]: r[key] for r in rows}

    def _by_row(rows):
        return {r["d"]: dict(r) for r in rows}

    # 1 积分消耗
    m = _by_day(await db.fetch_all(
        f"SELECT substr(finished_at,1,10) d, COALESCE(SUM(billable_credits),0) c"
        f" FROM task_records WHERE {COST} AND finished_at>=? GROUP BY d", (since,)), "c")
    consume = [{"t": d, "v": m.get(d, 0)} for d in day_series]

    # 2 任务量（total / completed / failed）
    m = _by_row(await db.fetch_all(
        "SELECT substr(submitted_at,1,10) d, COUNT(*) total,"
        " SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) done,"
        " SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failed"
        " FROM task_records WHERE submitted_at>=? GROUP BY d", (since,)))
    tasks = [{"t": d, "total": (m.get(d) or {}).get("total", 0),
              "completed": (m.get(d) or {}).get("done", 0),
              "failed": (m.get(d) or {}).get("failed", 0)} for d in day_series]

    # 3 充值（credited 的积分 + 金额）
    m = _by_row(await db.fetch_all(
        "SELECT substr(credited_at,1,10) d, COALESCE(SUM(credits),0) credits,"
        " COALESCE(SUM(amount_rmb),0) rmb FROM recharge_orders"
        " WHERE status='credited' AND credited_at>=? GROUP BY d", (since,)))
    recharge = [{"t": d, "credits": (m.get(d) or {}).get("credits", 0),
                 "rmb": (m.get(d) or {}).get("rmb", 0)} for d in day_series]

    # 4 用户增长（新增 + 累计，窗口前用户作 base）
    base = await db.scalar("SELECT COUNT(*) FROM users WHERE created_at<?", (since,), default=0)
    m = _by_day(await db.fetch_all(
        "SELECT substr(created_at,1,10) d, COUNT(*) c FROM users GROUP BY d"), "c")
    cum = base
    users = []
    for d in day_series:
        cum += m.get(d, 0)
        users.append({"t": d, "new": m.get(d, 0), "total": cum})

    # 5 成功率
    m = _by_row(await db.fetch_all(
        "SELECT substr(finished_at,1,10) d,"
        " SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) done,"
        " SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failed"
        " FROM task_records WHERE status IN ('completed','failed') AND finished_at>=? GROUP BY d",
        (since,)))
    success_rate = []
    for d in day_series:
        r = m.get(d)
        if r and (r["done"] or 0) + (r["failed"] or 0) > 0:
            success_rate.append({"t": d, "v": round(r["done"] / (r["done"] + r["failed"]), 3)})
        else:
            success_rate.append({"t": d, "v": None})

    # 6 平均耗时
    m = _by_day(await db.fetch_all(
        "SELECT substr(finished_at,1,10) d, AVG(duration_s) c FROM task_records"
        " WHERE duration_s IS NOT NULL AND finished_at>=? GROUP BY d", (since,)), "c")
    duration = [{"t": d, "v": (round(m[d], 1) if m.get(d) is not None else None)} for d in day_series]

    trend = {"days": days, "dates": day_series, "consume": consume, "tasks": tasks,
             "recharge": recharge, "users": users, "success_rate": success_rate,
             "duration": duration}

    return {"kpi": kpi, "pie": pie, "trend": trend, "generated_at": utcnow()}


# ------------------------------------------------------------------ 系统参数
class SettingIn(BaseModel):
    k: str
    v: str


@router.get("/admin/settings")
async def list_settings(request: Request, user: dict = Depends(require_admin)):
    """读全部系统参数（settings KV 表）；供管理界面展示/编辑。"""
    db = request.app.state.db
    rows = await db.fetch_all("SELECT k, v FROM settings ORDER BY k")
    return {"settings": {r["k"]: r["v"] for r in rows}}


@router.post("/admin/settings")
async def set_setting(request: Request, body: SettingIn,
                      user: dict = Depends(require_admin)):
    """写单个系统参数（k-v）；记审计。未来新增参数复用本接口。"""
    db = request.app.state.db
    k = (body.k or "").strip()
    if not k:
        raise BadRequest("参数键 k 不能为空")
    old = await db.get_setting(k, "")
    await db.set_setting(k, body.v)
    await _audit(db, user["id"], "set_setting", k, f"{old} -> {body.v}")
    return {"ok": True, "k": k, "v": body.v, "old": old}
