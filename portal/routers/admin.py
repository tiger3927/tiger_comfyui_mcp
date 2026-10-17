"""管理端 /admin/*（全量权限，require_admin；全部写操作记 admin_audit，
Task-WWW.md §6、§8）。"""
from __future__ import annotations

import json
import secrets
import time
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from schemas.models import ComfyUIConfig
from portal.accounts import grant_credits, set_password
from portal.routers.auth import _clear_login_fail
from portal.db import (COMFYUI_KV_DEFAULT, COMFYUI_KV_PRUNE_MODES,
                       COMFYUI_KV_ROUTING_PENDING, COMFYUI_KV_ROUTING_RUNNING,
                       utcnow)
from portal.errors import BadRequest, Conflict, NotFound
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


# 随机密码字母表：去易混淆字符（0 O 1 l I），便于微信转发/手抄
_PWD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def _gen_password(length: int = 12) -> str:
    while True:
        pwd = "".join(secrets.choice(_PWD_ALPHABET) for _ in range(length))
        if (any(c.islower() for c in pwd) and any(c.isupper() for c in pwd)
                and any(c.isdigit() for c in pwd)):
            return pwd


@router.post("/admin/users/{uid}/reset-password")
async def reset_password(request: Request, uid: int,
                         user: dict = Depends(require_admin)):
    """管理员重置用户密码：随机生成，仅本次响应返回（审计不存明文）。"""
    db = request.app.state.db
    row = await db.fetch_one("SELECT id, username FROM users WHERE id=?", (uid,))
    if row is None:
        raise NotFound("用户不存在")
    if uid == user["id"]:
        raise BadRequest("不能重置自己的密码（防误锁），请在账户页修改")
    new_pwd = _gen_password()
    await set_password(db, uid, new_pwd)
    _clear_login_fail(row["username"])  # 清掉旧密码试错残留的锁定
    await _audit(db, user["id"], "reset_password", str(uid),
                 f"target={row['username']}")
    return {"ok": True, "username": row["username"], "new_password": new_pwd}


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
        where.append("t.user_id IS NULL")
    elif uid:
        where.append("t.user_id=?")
        args.append(uid)
    if status:
        where.append("t.status=?")
        args.append(status)
    w = (" WHERE " + " AND ".join(where)) if where else ""
    rows = await db.fetch_all(
        "SELECT t.mcp_task_id, t.user_id, u.username, t.workflow_name, t.instance,"
        " t.status, t.billable_credits, t.submitted_at, t.finished_at"
        " FROM task_records t LEFT JOIN users u ON u.id=t.user_id" + w
        + " ORDER BY t.id DESC LIMIT 200", tuple(args))
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

    # ---------------- 实例总览（实时探针 + 按实例 DB 聚合，窗口=days）----------------
    # 探针 callable 由 main.py 注入（manager.status_all，同 MCP comfyui_status；
    # portal 包零 import core，红线不变）；未注入时全部离线降级展示。
    inst_rows = await db.fetch_all(
        "SELECT COALESCE(NULLIF(instance,''),'未标注') inst,"
        " COUNT(*) total,"
        " SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) completed,"
        " SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failed,"
        " SUM(CASE WHEN status IN ('pending','running') THEN 1 ELSE 0 END) active,"
        " ROUND(AVG(CASE WHEN duration_s IS NOT NULL THEN duration_s END),1) dur_avg"
        " FROM task_records WHERE submitted_at>=? GROUP BY inst", (since,))
    db_by_name = {r["inst"]: dict(r) for r in inst_rows}
    default_inst = await db.get_setting(COMFYUI_KV_DEFAULT, "")
    prov = getattr(request.app.state, "instances_provider", None)
    live: list[dict] = []
    if callable(prov):
        try:
            live = await prov()
        except Exception:
            live = []
    instances_out = []
    for i in live:
        name = i.get("name") or ""
        d = db_by_name.get(name, {})
        done = d.get("completed") or 0
        failed = d.get("failed") or 0
        denom = done + failed
        instances_out.append({
            "name": name,
            "url": i.get("url", ""),
            "connected": bool(i.get("connected")),
            "error": i.get("error", ""),
            "is_default": name == default_inst,
            "queue_pending": i.get("queue_pending"),
            "queue_running": i.get("queue_running"),
            "devices": i.get("devices") or [],
            "tasks_total": d.get("total") or 0,
            "tasks_active": d.get("active") or 0,
            "success_rate": round(done / denom, 3) if denom else None,
            "dur_avg": d.get("dur_avg"),
        })

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

    return {"kpi": kpi, "pie": pie, "instances": instances_out, "trend": trend,
            "generated_at": utcnow()}


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


# ------------------------------------------------------------------
# ComfyUI 实例管理（Task-DB-Config §3）：全量 require_admin + 写前整体校验
# （fail-fast 前移）+ 审计（comfyui_* 前缀，旧值→新值）+ 缓存 invalidate。
# 红线：本包零 import core/server——provider 失效与工作流名清单由 main.py
# 注入 app.state 的 callable 提供（与 task_provider 同一注入先例）。
# ------------------------------------------------------------------

class ComfyUIInstanceIn(BaseModel):
    name: str
    url: str
    password: str = ""


class ComfyUIInstancePatch(BaseModel):
    url: Optional[str] = None
    password: Optional[str] = None
    active: Optional[int] = None
    sort: Optional[int] = None


class ComfyUIRulesIn(BaseModel):
    only: list[str] = []
    exclude: list[str] = []


class ComfyUIWhitelistIn(BaseModel):
    entries: list[dict]  # [{pattern, active}]，整表替换


class ComfyUIDefaultIn(BaseModel):
    instance: str


class ComfyUIAdvancedIn(BaseModel):
    pending: Optional[float] = None
    running: Optional[float] = None
    prune_modes: Optional[dict[str, str]] = None


def _norm_url(url: str) -> str:
    v = (url or "").strip().rstrip("/")
    if not v:
        raise BadRequest("url 不能为空")
    return v


def _clean_patterns(pats: list[str]) -> list[str]:
    out: list[str] = []
    for p in pats or []:
        p = (p or "").strip()
        if p and p not in out:
            out.append(p)
    return out


def _invalidate(request: Request) -> None:
    """写完主动击穿 provider 缓存（main.py 注入；未注入时静默跳过）。"""
    fn = getattr(request.app.state, "invalidate_comfyui_config", None)
    if callable(fn):
        fn()


async def _validate_comfyui_state(db, default_must_be_active: bool = False) -> None:
    """写前整体校验（§3 fail-fast 前移）：事务内重读三表+KV 拼完整配置，
    与启动时同源校验（name 唯一非空 / url 归一化非空 / default 在实例名内）；
    PUT default 端点额外要求 default 为 active 实例。非法整单拒绝。"""
    insts = await db.fetch_all(
        "SELECT name, url, password FROM comfyui_instances ORDER BY sort, id")
    rules = await db.fetch_all(
        "SELECT rule_type FROM instance_workflow_rules")
    if any(r["rule_type"] not in ("only", "exclude") for r in rules):
        raise BadRequest("存在非法 rule_type")
    names = [i["name"] for i in insts]
    if len(set(names)) != len(names):
        raise BadRequest("实例名重复")
    for i in insts:
        if not (i["name"] or "").strip():
            raise BadRequest("存在空实例名")
        _norm_url(i["url"])  # 非法 url → BadRequest
    default = await db.get_setting(COMFYUI_KV_DEFAULT, "")
    if default and default not in names:
        raise BadRequest(f"default_instance {default!r} 不在实例列表中")
    if default_must_be_active:
        row = await db.fetch_one(
            "SELECT active FROM comfyui_instances WHERE name=?", (default,))
        if row is None or not row["active"]:
            raise BadRequest(f"default_instance 必须是启用（active=1）实例：{default!r}")


@router.get("/admin/comfyui/instances")
async def list_comfyui_instances(request: Request,
                                 user: dict = Depends(require_admin)):
    db = request.app.state.db
    insts = await db.fetch_all(
        "SELECT id, name, url, password, active, sort, created_at, updated_at"
        " FROM comfyui_instances ORDER BY sort, id")
    rules = await db.fetch_all(
        "SELECT instance_id, rule_type, pattern"
        " FROM instance_workflow_rules ORDER BY id")
    default = await db.get_setting(COMFYUI_KV_DEFAULT, "")
    by_inst: dict[int, dict] = {}
    for r in rules:
        d = by_inst.setdefault(r["instance_id"], {"only": [], "exclude": []})
        d[r["rule_type"]].append(r["pattern"])
    out = []
    for i in insts:
        d = dict(i)
        rr = by_inst.get(i["id"], {"only": [], "exclude": []})
        d["only"], d["exclude"] = rr["only"], rr["exclude"]
        d["is_default"] = i["name"] == default
        out.append(d)
    return {"instances": out}


@router.post("/admin/comfyui/instances")
async def create_comfyui_instance(request: Request, body: ComfyUIInstanceIn,
                                  user: dict = Depends(require_admin)):
    db = request.app.state.db
    name = (body.name or "").strip()
    if not name or len(name) > 64:
        raise BadRequest("name 需 1-64 字符")
    url = _norm_url(body.url)
    now = utcnow()
    async with db.transaction():
        row = await db.fetch_one(
            "SELECT id FROM comfyui_instances WHERE name=?", (name,))
        if row:
            raise Conflict(f"实例 {name!r} 已存在")
        mx = await db.scalar(
            "SELECT COALESCE(MAX(sort), -1) + 1 FROM comfyui_instances", default=0)
        cur = await db.execute(
            "INSERT INTO comfyui_instances"
            "(name, url, password, active, sort, created_at, updated_at)"
            " VALUES(?,?,?,?,1,?,?)", (name, url, body.password, mx, now, now))
        await _validate_comfyui_state(db)
        new_id = cur.lastrowid
    await _audit(db, user["id"], "comfyui_create_instance", name,
                 f"url={url} id={new_id}")
    _invalidate(request)
    return {"ok": True, "id": new_id}


@router.patch("/admin/comfyui/instances/{iid}")
async def update_comfyui_instance(request: Request, iid: int,
                                  body: ComfyUIInstancePatch,
                                  user: dict = Depends(require_admin)):
    db = request.app.state.db
    old = await db.fetch_one("SELECT * FROM comfyui_instances WHERE id=?", (iid,))
    if old is None:
        raise NotFound("实例不存在")
    changes: dict[str, str] = {}
    if body.url is not None:
        changes["url"] = _norm_url(body.url)
    if body.password is not None:
        changes["password"] = body.password
    if body.active is not None:
        if body.active not in (0, 1):
            raise BadRequest("active 只能 0/1")
        changes["active"] = body.active
    if body.sort is not None:
        changes["sort"] = body.sort
    if not changes:
        raise BadRequest("无可更新字段")
    async with db.transaction():
        sets = ", ".join(f"{k}=?" for k in changes)
        await db.execute(
            f"UPDATE comfyui_instances SET {sets}, updated_at=? WHERE id=?",
            (*changes.values(), utcnow(), iid))
        await _validate_comfyui_state(db)
    await _audit(db, user["id"], "comfyui_update_instance", old["name"],
                 " -> ".join(f"{k}: {old[k]!r} -> {v!r}"
                             for k, v in changes.items()))
    _invalidate(request)
    return {"ok": True}


@router.delete("/admin/comfyui/instances/{iid}")
async def delete_comfyui_instance(request: Request, iid: int,
                                  user: dict = Depends(require_admin)):
    """物理删除（§0-5）：校验非 default + 无在途任务（DB task_records +
    内存 TaskManager 双源）；CASCADE 清掉规则行。"""
    db = request.app.state.db
    row = await db.fetch_one("SELECT id, name FROM comfyui_instances WHERE id=?",
                             (iid,))
    if row is None:
        raise NotFound("实例不存在")
    name = row["name"]
    default = await db.get_setting(COMFYUI_KV_DEFAULT, "")
    if name == default:
        raise Conflict(f"{name!r} 是当前 default_instance，不能删除"
                       "（先 PUT /admin/comfyui/default 改默认）")
    n_db = await db.scalar(
        "SELECT COUNT(*) FROM task_records WHERE instance=? AND status IN"
        " ('pending','running')", (name,), default=0)
    n_mem = 0
    tp = getattr(request.app.state, "task_provider", None)
    if callable(tp):
        for t in tp():
            if t.get("instance") == name and \
                    t.get("status") in ("pending", "running"):
                n_mem += 1
    if n_db or n_mem:
        raise Conflict(f"实例 {name!r} 有在途任务（DB {n_db} / 内存 {n_mem}），"
                       "不能删除（可先禁用 active=0）")
    async with db.transaction():
        await db.execute("DELETE FROM comfyui_instances WHERE id=?", (iid,))
        await _validate_comfyui_state(db)
    await _audit(db, user["id"], "comfyui_delete_instance", name,
                 f"在途校验 db=0 mem=0 default={default!r}")
    _invalidate(request)
    return {"ok": True}


@router.put("/admin/comfyui/instances/{iid}/rules")
async def replace_comfyui_rules(request: Request, iid: int,
                                body: ComfyUIRulesIn,
                                user: dict = Depends(require_admin)):
    """整体替换该实例 only/exclude 的 pattern 列表（勾选矩阵提交格式）。"""
    db = request.app.state.db
    row = await db.fetch_one("SELECT id, name FROM comfyui_instances WHERE id=?",
                             (iid,))
    if row is None:
        raise NotFound("实例不存在")
    only = _clean_patterns(body.only)
    exclude = _clean_patterns(body.exclude)
    old_rules = await db.fetch_all(
        "SELECT rule_type, pattern FROM instance_workflow_rules WHERE instance_id=?"
        " ORDER BY id", (iid,))
    old = {"only": [r["pattern"] for r in old_rules if r["rule_type"] == "only"],
           "exclude": [r["pattern"] for r in old_rules
                       if r["rule_type"] == "exclude"]}
    async with db.transaction():
        await db.execute(
            "DELETE FROM instance_workflow_rules WHERE instance_id=?", (iid,))
        for pat in only:
            await db.execute(
                "INSERT INTO instance_workflow_rules(instance_id, rule_type, pattern)"
                " VALUES(?,?,?)", (iid, "only", pat))
        for pat in exclude:
            await db.execute(
                "INSERT INTO instance_workflow_rules(instance_id, rule_type, pattern)"
                " VALUES(?,?,?)", (iid, "exclude", pat))
        await _validate_comfyui_state(db)
    await _audit(db, user["id"], "comfyui_replace_rules", row["name"],
                 f"only {old['only']} -> {only}; exclude {old['exclude']}"
                 f" -> {exclude}")
    _invalidate(request)
    return {"ok": True}


@router.get("/admin/comfyui/whitelist")
async def get_comfyui_whitelist(request: Request,
                                user: dict = Depends(require_admin)):
    db = request.app.state.db
    rows = await db.fetch_all(
        "SELECT id, pattern, active FROM workflow_whitelist ORDER BY id")
    return {"entries": [dict(r) for r in rows]}


@router.put("/admin/comfyui/whitelist")
async def put_comfyui_whitelist(request: Request, body: ComfyUIWhitelistIn,
                                user: dict = Depends(require_admin)):
    """全局白名单整表替换（行 = pattern + active；active=0 等价移出白名单）。
    注意：全部 active=0 = 全不放行（fail-closed）。"""
    db = request.app.state.db
    entries: list[tuple[str, int]] = []
    for e in body.entries:
        pat = (str(e.get("pattern") or "")).strip()
        if not pat:
            raise BadRequest("白名单 pattern 不能为空")
        entries.append((pat, 1 if e.get("active") else 0))
    if len({p for p, _ in entries}) != len(entries):
        raise BadRequest("白名单 pattern 重复")
    old_rows = await db.fetch_all(
        "SELECT pattern, active FROM workflow_whitelist ORDER BY id")
    old = {r["pattern"]: r["active"] for r in old_rows}
    async with db.transaction():
        await db.execute("DELETE FROM workflow_whitelist")
        for pat, active in entries:
            await db.execute(
                "INSERT INTO workflow_whitelist(pattern, active) VALUES(?,?)",
                (pat, active))
        await _validate_comfyui_state(db)
    new = {p: a for p, a in entries}
    await _audit(db, user["id"], "comfyui_replace_whitelist",
                 str(len(entries)), f"{old} -> {new}")
    _invalidate(request)
    return {"ok": True}


@router.put("/admin/comfyui/default")
async def set_comfyui_default(request: Request, body: ComfyUIDefaultIn,
                              user: dict = Depends(require_admin)):
    db = request.app.state.db
    name = (body.instance or "").strip()
    old = await db.get_setting(COMFYUI_KV_DEFAULT, "")
    row = await db.fetch_one(
        "SELECT active FROM comfyui_instances WHERE name=?", (name,))
    if row is None:
        raise NotFound(f"实例 {name!r} 不存在")
    if not row["active"]:
        raise BadRequest(f"实例 {name!r} 已禁用，不能设为 default（写端校验）")
    await db.set_setting(COMFYUI_KV_DEFAULT, name)
    await _audit(db, user["id"], "comfyui_set_default", name, f"{old!r} -> {name!r}")
    _invalidate(request)
    return {"ok": True, "default": name, "old": old}


@router.get("/admin/comfyui/advanced")
async def get_comfyui_advanced(request: Request,
                               user: dict = Depends(require_admin)):
    db = request.app.state.db
    default = await db.get_setting(COMFYUI_KV_DEFAULT, "")
    pending = await db.get_setting(COMFYUI_KV_ROUTING_PENDING, "1.0")
    running = await db.get_setting(COMFYUI_KV_ROUTING_RUNNING, "2.0")
    prune_raw = await db.get_setting(COMFYUI_KV_PRUNE_MODES, "{}")
    try:
        prune = json.loads(prune_raw or "{}")
    except Exception:
        raise BadRequest("comfyui.prune_modes KV 损坏（非 JSON）")
    return {"default_instance": default, "pending": float(pending),
            "running": float(running), "prune_modes": prune}


@router.put("/admin/comfyui/advanced")
async def put_comfyui_advanced(request: Request, body: ComfyUIAdvancedIn,
                               user: dict = Depends(require_admin)):
    """routing.weights + workflow_prune_modes（KV 读写 + 同源校验）。"""
    db = request.app.state.db
    if body.pending is not None and body.pending < 0:
        raise BadRequest("routing.pending 必须 ≥ 0")
    if body.running is not None and body.running < 0:
        raise BadRequest("routing.running 必须 ≥ 0")
    if body.prune_modes is not None:
        # 与启动时同源的制度名校验（ComfyUIConfig 的 field_validator）
        from pydantic import ValidationError
        try:
            ComfyUIConfig.model_validate({
                "comfyui_instances": [], "default_instance": "x",
                "workflow_prune_modes": body.prune_modes})
        except ValidationError as e:
            raise BadRequest(f"prune_modes 校验失败：{e.errors()[0]['msg']}"
                             if e.errors() else "prune_modes 校验失败")
    old: dict[str, str] = {}
    if body.pending is not None:
        old["pending"] = await db.get_setting(COMFYUI_KV_ROUTING_PENDING, "1.0")
        await db.set_setting(COMFYUI_KV_ROUTING_PENDING, repr(float(body.pending)))
    if body.running is not None:
        old["running"] = await db.get_setting(COMFYUI_KV_ROUTING_RUNNING, "2.0")
        await db.set_setting(COMFYUI_KV_ROUTING_RUNNING, repr(float(body.running)))
    if body.prune_modes is not None:
        old["prune_modes"] = await db.get_setting(COMFYUI_KV_PRUNE_MODES, "{}")
        await db.set_setting(COMFYUI_KV_PRUNE_MODES,
                             json.dumps(body.prune_modes, ensure_ascii=False))
    if not old:
        raise BadRequest("无可更新字段")
    await _audit(db, user["id"], "comfyui_update_advanced", "",
                 " -> ".join(f"{k}: {v}" for k, v in old.items())
                 + " => 新值已写入")
    _invalidate(request)
    return {"ok": True}


@router.get("/admin/comfyui/workflow-names")
async def list_comfyui_workflow_names(request: Request,
                                      user: dict = Depends(require_admin)):
    """workflows_dir 全量文件名（支撑勾选矩阵行；callable 由 main.py 注入）。"""
    fn = getattr(request.app.state, "workflow_names_provider", None)
    names = fn() if callable(fn) else []
    return {"names": sorted(names)}
