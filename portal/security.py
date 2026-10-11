"""门户安全：argon2 口令哈希 + JWT(HS256) 签发/校验 + FastAPI 鉴权依赖。

门户 JWT 独立于 mcp Bearer 体系（§8-5）：Bearer 管"能不能调服务"，本 JWT 管
"门户页面登录态"；user token（§4 user_tokens）是第三套，管"任务记谁账上"。
"""
from __future__ import annotations

import time
from typing import Any, Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, Request

from portal.config import PortalSettings
from portal.db import PortalDB
from portal.errors import Forbidden, Unauthorized

_ph = PasswordHasher()

# argon2 参数（内存 64MiB / 3 迭代 / 并行 4）——注册/登录频次极低，成本可接受
def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return _ph.verify(encoded, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(encoded: str) -> bool:
    try:
        return _ph.check_needs_rehash(encoded)
    except InvalidHashError:
        return True


# ------------------------------------------------------------------ JWT
def create_jwt(user_id: int, role: str, settings: PortalSettings,
               *, now: Optional[float] = None) -> str:
    if not settings.has_jwt_secret:
        raise RuntimeError("未配置 portal.jwt_secret / PORTAL_JWT_SECRET，无法签发 JWT")
    iat = int(now if now is not None else time.time())
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": iat,
        "exp": iat + settings.jwt_ttl_hours * 3600,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_jwt(token: str, settings: PortalSettings,
               *, now: Optional[float] = None) -> dict[str, Any]:
    if not settings.has_jwt_secret:
        raise Unauthorized("门户未配置 JWT 密钥")
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"],
                          options={"verify_aud": False})
    except jwt.PyJWTError:
        raise Unauthorized("登录态无效或已过期，请重新登录")


def _bearer(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return ""


# --------------------------------------------------- FastAPI 依赖（M3 起用）
async def get_current_user(request: Request) -> dict[str, Any]:
    """解析 Bearer JWT → 载入并返回用户行（dict）；停用用户拒绝。"""
    token = _bearer(request)
    if not token:
        raise Unauthorized("缺少 Authorization: Bearer <jwt>")
    settings: PortalSettings = request.app.state.portal_settings
    db: PortalDB = request.app.state.db
    claims = decode_jwt(token, settings)
    row = await db.fetch_one(
        "SELECT id, username, role, balance, active_count, disabled, created_at"
        " FROM users WHERE id=?", (int(claims["sub"]),))
    if row is None:
        raise Unauthorized("用户不存在")
    if row["disabled"]:
        raise Forbidden("账户已停用")
    return dict(row)


async def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise Forbidden("需要管理员权限")
    return user
