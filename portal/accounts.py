"""账户与 token 操作 + ledger 授予/调整统一入口（§4、§8-1）。

规则：一切 balance 变动只经 credit_ledger（§3）——本模块 grant/adjust 写 ledger
并同步 users.balance；freeze/settle/refund 的余额流在 billing.py。
"""
from __future__ import annotations

import re
import secrets
from typing import Optional

from portal.billing import hash_token  # 单一实现（与 core.manager 提交侧同算法）
from portal.db import PortalDB, utcnow
from portal.errors import BadRequest, Conflict, NotFound
from portal.security import hash_password

USER_RE = re.compile(r"^[A-Za-z0-9_.-]{4,32}$")
TOKEN_PREFIX = "pt_"


# ------------------------------------------------------------------ 用户
async def create_user(db: PortalDB, username: str, password: str,
                      *, role: str = "user") -> int:
    username = (username or "").strip()
    if not USER_RE.match(username):
        raise BadRequest("用户名需 4–32 位，仅限字母/数字/_-.")
    if not password or len(password) < 8:
        raise BadRequest("密码至少 8 位")
    exists = await db.fetch_one("SELECT id FROM users WHERE username=?", (username,))
    if exists:
        raise Conflict(f"用户名已存在：{username}")
    ph = hash_password(password)
    cur = await db.execute(
        "INSERT INTO users(username, pass_hash, role, balance, active_count,"
        " created_at, disabled) VALUES(?,?,?,0,0,?,0)",
        (username, ph, role, utcnow()))
    uid = cur.lastrowid
    # 建号也走流水（§3）：0 元 seed 作为余额对账锚点（无 token，token_id=NULL）
    await db.execute(
        "INSERT INTO credit_ledger(user_id, token_id, delta, kind, ref_kind, ref_id,"
        " balance_after, note, created_at) VALUES(?,NULL,0,'seed','user',?,0,?,?)",
        (uid, str(uid), f"建号初始（{role}）", utcnow()))
    return uid


async def set_password(db: PortalDB, user_id: int, new_password: str) -> None:
    if not new_password or len(new_password) < 8:
        raise BadRequest("密码至少 8 位")
    await db.execute("UPDATE users SET pass_hash=? WHERE id=?",
                     (hash_password(new_password), user_id))


# ------------------------------------------------------------- 余额授予/调整
async def grant_credits(db: PortalDB, *, user_id: int, delta: int, kind: str,
                        ref_kind: str, ref_id: str, note: str = "",
                        token_id: Optional[int] = None,
                        allow_negative: bool = False) -> int:
    """写 ledger 并同步 users.balance（充值/调整用；幂等靠 ledger 唯一约束）。

    返回记账后余额。kind ∈ recharge/adjust；负 delta 默认不得把余额扣成负（§8-8）。
    """
    async with db.transaction() as tx:
        cur = await tx.execute(
            "SELECT balance FROM users WHERE id=?", (user_id,))
        row = await cur.fetchone()
        await cur.close()
        if row is None:
            raise NotFound(f"用户不存在：{user_id}")
        balance = row[0]
        new_balance = balance + delta
        if not allow_negative and new_balance < 0:
            raise BadRequest(f"调整后将透支余额（当前 {balance}，delta {delta}），已拒绝")
        cur = await tx.execute(
            "INSERT OR IGNORE INTO credit_ledger"
            "(user_id, token_id, delta, kind, ref_kind, ref_id, balance_after, note,"
            " created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (user_id, token_id, delta, kind, ref_kind, ref_id, new_balance, note,
             utcnow()))
        if cur.rowcount == 0:
            # 幂等：同 (kind,ref_kind,ref_id) 已记过 → 不重复入账，回读既有余额
            cur2 = await tx.execute(
                "SELECT balance_after FROM credit_ledger WHERE kind=? AND ref_kind=?"
                " AND ref_id=?", (kind, ref_kind, ref_id))
            ex = await cur2.fetchone()
            await cur2.close()
            return ex[0] if ex else balance
        await tx.execute("UPDATE users SET balance=? WHERE id=?",
                         (new_balance, user_id))
        return new_balance


# ------------------------------------------------------------------ Token
async def create_token(db: PortalDB, user_id: int, name: str,
                       *, credit_limit: int = 0,
                       expires_at: Optional[str] = None) -> tuple[int, str]:
    """申请 user token；明文存库（token_plain）+ sha256 哈希（token_hash）+ 前缀。"""
    name = (name or "").strip()
    if not name:
        raise BadRequest("token 名称不能为空")
    if credit_limit < 0:
        raise BadRequest("credit_limit 不能为负（0=不设上限）")
    plain = TOKEN_PREFIX + secrets.token_urlsafe(32)
    th = hash_token(plain)
    cur = await db.execute(
        "INSERT INTO user_tokens(user_id, name, token_hash, token_prefix, token_plain,"
        " credit_limit, used, expires_at, disabled, created_at)"
        " VALUES(?,?,?,?,?,?,0,?,0,?)",
        (user_id, name, th, plain[:10], plain, credit_limit, expires_at, utcnow()))
    return cur.lastrowid, plain


async def token_remaining(db: PortalDB, token_id: int) -> Optional[int]:
    from portal.billing import token_remaining as _tr
    row = await db.fetch_one(
        "SELECT u.balance, t.credit_limit, t.used FROM user_tokens t"
        " JOIN users u ON u.id=t.user_id WHERE t.id=?", (token_id,))
    if row is None:
        return None
    return _tr(row["balance"], row["credit_limit"], row["used"])
