"""门户计费引擎：产物计价（§3.1）+ 提交预检冻结 / 终态结算 / 退款（§3.2、§5.2）。

红线（§2.1）：precheck 的"校验"与 freeze 必须同事务——本模块所有余额/在途数
变动都在 `db.transaction()`（BEGIN IMMEDIATE）内读→判→写，杜绝并发双双过检。
计价同源：estimate 是 precheck 估算与 settle 重算的唯一入口，口径不漂移。
"""
from __future__ import annotations

import fnmatch
import hashlib
import logging
import math
from typing import Any, Optional

from portal.config import PortalSettings
from portal.db import PortalDB, utcnow
from portal.errors import (
    ActiveLimitExceeded, AnonymousBlocked, InsufficientCredits,
    InvalidToken, TokenLimitExceeded,
)

logger = logging.getLogger("portal.billing")

DEFAULT_FPS = 24


# ============================================================ 计价（§3.1）
async def _match_rule(db: PortalDB, workflow_name: str) -> Optional[dict]:
    """active 规则里取第一条 fnmatch 命中 workflow_name 的（一行一工作流）。"""
    rows = await db.fetch_all(
        "SELECT * FROM credit_rules WHERE active=1 ORDER BY id")
    for r in rows:
        if fnmatch.fnmatchcase(workflow_name, r["pattern"]):
            return dict(r)
    return None


def _num(params: dict, key: Optional[str]) -> Optional[float]:
    if not key:
        return None
    v = params.get(key)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def token_remaining(balance: int, credit_limit: int, used: int) -> int:
    """token 剩余可用（§3.3-A）：min(用户余额, 上限−该 token 累计已消费)；0=不限。"""
    if credit_limit and credit_limit > 0:
        return max(0, min(balance, credit_limit - used))
    return max(0, balance)


async def estimate_credits(db: PortalDB, settings: PortalSettings,
                           workflow_name: str,
                           params: dict[str, Any] | None) -> tuple[int, bool, dict]:
    """返回 (积分, 是否命中规则, 计费要素摘要)。未命中 → default_price + matched=False。"""
    params = params or {}
    rule = await _match_rule(db, workflow_name)
    if rule is None:
        logger.warning("[billing] 工作流 %r 未命中任何 credit_rules，按 default_price=%d",
                       workflow_name, settings.default_price)
        return settings.default_price, False, {"reason": "unmatched_rule"}

    media = rule["media"]
    if media == "flat":
        return int(rule["flat_price"]), True, {"media": "flat"}

    if media == "audio":
        text = params.get(rule["char_param"]) if rule["char_param"] else None
        chars = len(str(text)) if text else 0
        credits = math.ceil(rule["price_per_char"] * chars / 100.0) if chars else 0
        if chars and credits < 1:
            credits = 1
        return credits, True, {"media": "audio", "chars": chars}

    # image / video：解析 W/H（参数键优先，回落默认分辨率）
    w = _num(params, rule["width_param"])
    if not w:
        w = rule["default_width"] or 0
    h = _num(params, rule["height_param"])
    if not h:
        h = rule["default_height"] or 0
    if w <= 0 or h <= 0:
        logger.warning("[billing] %r 无法解析分辨率（W=%s H=%s），按 default_price",
                       workflow_name, w, h)
        return settings.default_price, False, {"reason": "unresolved_size",
                                               "w": w, "h": h}
    mp = w * h / 1e6
    if media == "image":
        credits = math.ceil(rule["price_per_mp"] * mp)
        return credits, True, {"media": "image", "w": int(w), "h": int(h),
                               "mp": round(mp, 4)}
    if media == "video":
        sec = _num(params, rule["seconds_param"]) or 0
        fps = rule["fps"] or DEFAULT_FPS
        if sec <= 0:
            logger.warning("[billing] 视频 %r 无有效时长（seconds_param=%r）",
                           workflow_name, rule["seconds_param"])
            return settings.default_price, False, {"reason": "unresolved_seconds"}
        # 锚点按"每秒"取整再乘秒数（§3.1），避免整段乘积浮点取整 off-by-one
        per_second = round(rule["price_per_mp"] * mp * fps)
        credits = round(per_second * sec)
        return credits, True, {"media": "video", "w": int(w), "h": int(h),
                               "seconds": sec, "fps": fps, "mp": round(mp, 4)}
    return settings.default_price, False, {"reason": "unknown_media", "media": media}


# ====================================================== 身份 / 令牌解析
def hash_token(token_plain: str) -> str:
    return hashlib.sha256(token_plain.encode("utf-8")).hexdigest()


async def resolve_user_token(db: PortalDB, token_plain: str) -> tuple[dict, dict]:
    """明文 user token → (user_row, token_row)。停用/过期/禁用一律拒绝。"""
    th = hash_token(token_plain)
    row = await db.fetch_one(
        "SELECT u.id AS uid, u.username, u.role, u.balance, u.active_count,"
        " u.disabled AS u_disabled,"
        " t.id AS tid, t.name, t.credit_limit, t.used, t.expires_at,"
        " t.disabled AS t_disabled"
        " FROM user_tokens t JOIN users u ON u.id = t.user_id"
        " WHERE t.token_hash = ?", (th,))
    if row is None:
        raise InvalidToken("token 无效（不存在）")
    if row["t_disabled"]:
        raise InvalidToken("token 已停用")
    if row["u_disabled"]:
        raise InvalidToken("账户已停用")
    if row["expires_at"] and row["expires_at"] < utcnow():
        raise InvalidToken("token 已过期")
    return dict(row), dict(row)  # 同一行拆两份语义（user/token）


# ====================================================== 预检 + 冻结（§5.2）
async def precheck_and_freeze(db: PortalDB, settings: PortalSettings,
                              workflow_name: str, params: dict[str, Any],
                              token_plain: Optional[str], task_id: str) -> dict:
    """提交前调用：校验余额/上限/在途数 → 同事务 freeze（预扣全额 + active_count+1）。

    抛 PortalError 子类即"提交即拒"。返回 {credits, matched, digest, user_id, token_id}。
    """
    allow_anon = (await db.get_setting("allow_anonymous", "1")) == "1"
    if not token_plain:
        if allow_anon:
            return {"credits": 0, "matched": True, "digest": {"anonymous": True},
                    "user_id": None, "token_id": None, "anonymous": True}
        raise AnonymousBlocked("未提供 user token，且门户已关闭匿名任务")

    _, ident = await resolve_user_token(db, token_plain)
    uid, tid = ident["uid"], ident["tid"]
    est, matched, digest = await estimate_credits(db, settings, workflow_name, params)

    async with db.transaction() as tx:
        cur = await tx.execute(
            "SELECT balance, active_count FROM users WHERE id=? AND disabled=0", (uid,))
        urow = await cur.fetchone()
        await cur.close()
        if urow is None:
            raise InvalidToken("账户已停用")
        balance, active = urow[0], urow[1]
        cur = await tx.execute(
            "SELECT credit_limit, used FROM user_tokens WHERE id=? AND disabled=0", (tid,))
        trow = await cur.fetchone()
        await cur.close()
        if trow is None:
            raise InvalidToken("token 已停用")
        credit_limit, used = trow[0], trow[1]

        if settings.max_active_per_user > 0 and active >= settings.max_active_per_user:
            raise ActiveLimitExceeded(
                f"在途任务已达上限 {settings.max_active_per_user}，请等待完成后再提交")

        remaining = token_remaining(balance, credit_limit, used)
        if est > balance:
            raise InsufficientCredits(f"积分不足：需 {est}，余额 {balance}")
        if credit_limit > 0 and used + est > credit_limit:
            raise TokenLimitExceeded(
                f"超出 token 上限：该 token 已用 {used}，上限 {credit_limit}，本次需 {est}")

        new_balance = balance - est
        await tx.execute(
            "UPDATE users SET balance=?, active_count=active_count+1 WHERE id=?",
            (new_balance, uid))
        if est != 0:
            await tx.execute(
                "INSERT OR IGNORE INTO credit_ledger"
                "(user_id, token_id, delta, kind, ref_kind, ref_id, balance_after, note,"
                " created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (uid, tid, -est, "freeze", "task", task_id, new_balance,
                 f"{workflow_name} 预扣", utcnow()))

    return {"credits": est, "matched": matched, "digest": digest,
            "user_id": uid, "token_id": tid}


# ========================================================= 终态结算（§3.2）
async def settle(db: PortalDB, settings: PortalSettings, *, task_id: str,
                 user_id: int, token_id: Optional[int], workflow_name: str,
                 actual_params: dict[str, Any] | None) -> int:
    """SUCCESS：按最终参数重算 → freeze 转 spend / 补差退差；active_count-1。幂等。"""
    est_actual, _, digest = await estimate_credits(db, settings, workflow_name,
                                                   actual_params or {})
    async with db.transaction() as tx:
        # 幂等：已 settle/refund 过则跳过
        cur = await tx.execute(
            "SELECT 1 FROM credit_ledger WHERE ref_kind='task' AND ref_id=?"
            " AND kind IN ('settle','refund')", (task_id,))
        if await cur.fetchone():
            await cur.close()
            return est_actual
        cur = await tx.execute(
            "SELECT delta FROM credit_ledger WHERE kind='freeze'"
            " AND ref_kind='task' AND ref_id=?", (task_id,))
        frow = await cur.fetchone()
        await cur.close()
        est_freeze = -(frow[0]) if frow else 0

        cur = await tx.execute("SELECT balance FROM users WHERE id=?", (user_id,))
        urow = await cur.fetchone()
        await cur.close()
        balance = urow[0] if urow else 0

        adjustment = est_freeze - est_actual       # >0 退差，<0 补差
        new_balance = balance + adjustment
        await tx.execute(
            "UPDATE users SET balance=?, active_count=MAX(active_count-1,0) WHERE id=?",
            (new_balance, user_id))
        if token_id is not None:
            await tx.execute(
                "UPDATE user_tokens SET used=used+? WHERE id=?", (est_actual, token_id))
        await tx.execute(
            "INSERT OR IGNORE INTO credit_ledger"
            "(user_id, token_id, delta, kind, ref_kind, ref_id, balance_after, note,"
            " created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (user_id, token_id, adjustment, "settle", "task", task_id, new_balance,
             f"{workflow_name} 结算={est_actual}（冻结{est_freeze}）", utcnow()))
    return est_actual


# =========================================================== 退款（§3.2）
async def refund(db: PortalDB, settings: PortalSettings, *, task_id: str,
                 user_id: int, token_id: Optional[int], reason: str = "failed",
                 workflow_name: str = "", runtime_seconds: float = 0.0,
                 full_params: dict[str, Any] | None = None) -> int:
    """FAILED/TIMEOUT 全额退；CANCELLED 按 §3.2 计费下限收。active_count-1。幂等。

    返回本次实际收取积分（charged）。
    """
    async with db.transaction() as tx:
        cur = await tx.execute(
            "SELECT 1 FROM credit_ledger WHERE ref_kind='task' AND ref_id=?"
            " AND kind IN ('settle','refund')", (task_id,))
        if await cur.fetchone():
            await cur.close()
            return 0
        cur = await tx.execute(
            "SELECT delta FROM credit_ledger WHERE kind='freeze'"
            " AND ref_kind='task' AND ref_id=?", (task_id,))
        frow = await cur.fetchone()
        await cur.close()
        est_freeze = -(frow[0]) if frow else 0

        charged = 0
        if reason == "cancelled" and est_freeze > 0:
            charged = await _cancel_floor(tx, settings, workflow_name,
                                          est_freeze, runtime_seconds,
                                          full_params or {})
            charged = max(0, min(charged, est_freeze))
        refund_delta = est_freeze - charged

        cur = await tx.execute("SELECT balance FROM users WHERE id=?", (user_id,))
        urow = await cur.fetchone()
        await cur.close()
        balance = urow[0] if urow else 0
        new_balance = balance + refund_delta
        await tx.execute(
            "UPDATE users SET balance=?, active_count=MAX(active_count-1,0) WHERE id=?",
            (new_balance, user_id))
        if token_id is not None and charged > 0:
            await tx.execute(
                "UPDATE user_tokens SET used=used+? WHERE id=?", (charged, token_id))
        await tx.execute(
            "INSERT OR IGNORE INTO credit_ledger"
            "(user_id, token_id, delta, kind, ref_kind, ref_id, balance_after, note,"
            " created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (user_id, token_id, refund_delta, "refund", "task", task_id, new_balance,
             f"{reason} 退款（收{charged}/冻{est_freeze}）", utcnow()))
    return charged


async def _cancel_floor(tx, settings: PortalSettings, workflow_name: str,
                        est_freeze: int, runtime_seconds: float,
                        params: dict[str, Any]) -> int:
    """CANCELLED 计费下限：max(已运行秒×档价, 档价×20%)，封顶全额（§3.2、§13-7）。

    非视频/无有效秒数 → 20% 全额下限。
    """
    floor20 = math.ceil(est_freeze * 0.2)
    rt_credits = 0
    if workflow_name and runtime_seconds and runtime_seconds > 0:
        # 用同一规则按"实际已运行秒数"重算（视频类 seconds 覆盖）
        rule = await _match_rule_conn(tx, workflow_name)
        if rule and rule["media"] == "video":
            p2 = dict(params)
            if rule["seconds_param"]:
                p2[rule["seconds_param"]] = runtime_seconds
            w = _num(p2, rule["width_param"]) or (rule["default_width"] or 0)
            h = _num(p2, rule["height_param"]) or (rule["default_height"] or 0)
            if w > 0 and h > 0:
                fps = rule["fps"] or DEFAULT_FPS
                rt_credits = math.ceil(rule["price_per_mp"] * (w * h / 1e6)
                                       * runtime_seconds * fps)
    return max(rt_credits, floor20)


async def _match_rule_conn(tx, workflow_name: str) -> Optional[dict]:
    cur = await tx.execute(
        "SELECT * FROM credit_rules WHERE active=1 ORDER BY id")
    rows = await cur.fetchall()
    await cur.close()
    for r in rows:
        if fnmatch.fnmatchcase(workflow_name, r["pattern"]):
            return dict(r)
    return None
