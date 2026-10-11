"""认证：注册 / 登录（Task-WWW.md §6）。登录态 = 门户 JWT（独立于 mcp Bearer）。"""
from __future__ import annotations

import base64
import random
import secrets
import time
import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel

from portal.accounts import create_user, grant_credits
from portal.errors import BadRequest, Forbidden, Unauthorized
from portal.security import create_jwt, verify_password

router = APIRouter(tags=["auth"])

# --- 图形验证码（纯 SVG，零第三方依赖；单进程内存存储）---
# 字符集剔除易混的 0/O/1/I/L；固定 4 位；60s 过期；一次性（校验即消费）
_CAPTCHA_CHARS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_CAPTCHA_TTL = 60.0
_CAPTCHA_STORE: dict[str, dict] = {}  # {captcha_id: {"code": str, "expires_at": float}}


def _cleanup_captcha() -> None:
    now = time.time()
    for k in [k for k, v in _CAPTCHA_STORE.items() if v["expires_at"] < now]:
        _CAPTCHA_STORE.pop(k, None)


def _render_svg(code: str) -> str:
    """把 4 位验证码画成带干扰线/噪点/字符旋转的 SVG（零依赖，纯文本）。"""
    w, h = 120, 40
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
         f'viewBox="0 0 {w} {h}">']
    p.append(f'<rect width="{w}" height="{h}" fill="#f5f6f8"/>')
    for _ in range(6):  # 干扰线
        c = f"rgb({random.randint(120, 210)},{random.randint(120, 210)},{random.randint(120, 210)})"
        p.append(f'<line x1="{random.randint(0, w)}" y1="{random.randint(0, h)}" '
                 f'x2="{random.randint(0, w)}" y2="{random.randint(0, h)}" '
                 f'stroke="{c}" stroke-width="1"/>')
    for _ in range(50):  # 噪点
        c = f"rgb({random.randint(150, 255)},{random.randint(150, 255)},{random.randint(150, 255)})"
        p.append(f'<circle cx="{random.randint(0, w)}" cy="{random.randint(0, h)}" '
                 f'r="1" fill="{c}"/>')
    n = max(len(code), 1)
    for i, ch in enumerate(code):
        x = 14 + i * (w - 32) / n + random.randint(-3, 3)
        y = 28 + random.randint(-4, 4)
        angle = random.randint(-28, 28)
        c = f"rgb({random.randint(20, 110)},{random.randint(20, 110)},{random.randint(20, 110)})"
        p.append(f'<text x="{x}" y="{y}" font-family="monospace" font-size="26" '
                 f'font-weight="bold" fill="{c}" '
                 f'transform="rotate({angle} {x} {y})">{ch}</text>')
    p.append('</svg>')
    return ''.join(p)


def _verify_captcha(captcha_id: str, code: str) -> None:
    """校验并消费（一次性）验证码；缺失/过期/错误均抛 BadRequest。"""
    _cleanup_captcha()
    entry = _CAPTCHA_STORE.pop(captcha_id, None)
    if entry is None:
        raise BadRequest("验证码已失效，请刷新后重试")
    if (code or "").strip().upper() != entry["code"]:
        raise BadRequest("验证码错误")


# --- 登录限流（防暴力破解；单进程内存，按用户名；失败 N 次锁定 5 分钟）---
_LOGIN_MAX_FAILS = 5
_LOGIN_LOCK_SECONDS = 300.0
_LOGIN_FAIL: dict[str, dict] = {}  # {username: {"fails": int, "locked_until": float}}


def _is_login_locked(username: str) -> int:
    """若该用户名处于锁定中，返回剩余秒数；否则 0。"""
    entry = _LOGIN_FAIL.get(username)
    if entry and entry["locked_until"] > time.time():
        return int(entry["locked_until"] - time.time())
    return 0


def _record_login_fail(username: str) -> None:
    """记录一次登录失败；达到阈值锁定 5 分钟。"""
    now = time.time()
    entry = _LOGIN_FAIL.get(username, {"fails": 0, "locked_until": 0.0})
    if entry["locked_until"] and entry["locked_until"] < now:  # 旧锁已过期 → 重置计数
        entry = {"fails": 0, "locked_until": 0.0}
    entry["fails"] += 1
    if entry["fails"] >= _LOGIN_MAX_FAILS:
        entry["locked_until"] = now + _LOGIN_LOCK_SECONDS
        entry["fails"] = 0
    _LOGIN_FAIL[username] = entry


def _clear_login_fail(username: str) -> None:
    """登录成功 → 清除该用户名失败计数/锁定。"""
    _LOGIN_FAIL.pop(username, None)


class _Creds(BaseModel):
    username: str
    password: str
    captcha_id: str = ""
    captcha_code: str = ""


@router.get("/auth/captcha")
async def get_captcha():
    """生成图形验证码（登录/注册前调用）。返回 captcha_id + base64 SVG 图片。"""
    _cleanup_captcha()
    code = "".join(secrets.choice(_CAPTCHA_CHARS) for _ in range(4))
    captcha_id = uuid.uuid4().hex
    _CAPTCHA_STORE[captcha_id] = {"code": code, "expires_at": time.time() + _CAPTCHA_TTL}
    svg = _render_svg(code)
    image = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return {"captcha_id": captcha_id, "image": image, "expires_in": int(_CAPTCHA_TTL)}


@router.post("/auth/register")
async def register(body: _Creds, request: Request):
    _verify_captcha(body.captcha_id, body.captcha_code)
    db = request.app.state.db
    settings = request.app.state.portal_settings
    if (await db.get_setting("registration_open", "1")) != "1":
        raise BadRequest("注册已关闭（内测/公网策略），请联系管理员")
    if not settings.has_jwt_secret:
        raise BadRequest("门户未配置 JWT 密钥，无法注册")
    uid = await create_user(db, body.username, body.password, role="user")
    # 新用户注册赠送积分（系统参数 new_user_bonus_credits；幂等：每用户一次）
    bonus = 0
    try:
        bonus = int(await db.get_setting("new_user_bonus_credits", "10000") or 0)
    except (TypeError, ValueError):
        bonus = 0
    if bonus > 0:
        await grant_credits(db, user_id=uid, delta=bonus, kind="register_bonus",
                            ref_kind="user", ref_id=str(uid),
                            note=f"新用户注册赠送 {bonus} 积分")
    row = await db.fetch_one(
        "SELECT id, username, role, balance FROM users WHERE id=?", (uid,))
    return {"token": create_jwt(uid, "user", settings), "user": dict(row)}


@router.post("/auth/login")
async def login(body: _Creds, request: Request):
    # 1) 锁定检查（最高优先级：锁定期间即使密码正确也拒绝，防暴力破解）
    remaining = _is_login_locked(body.username)
    if remaining:
        raise Forbidden(f"登录失败次数过多，已锁定，请 {remaining} 秒后重试")
    # 2) 校验验证码（一次性）
    _verify_captcha(body.captcha_id, body.captcha_code)
    db = request.app.state.db
    settings = request.app.state.portal_settings
    row = await db.fetch_one(
        "SELECT id, username, role, balance, disabled, pass_hash FROM users"
        " WHERE username=?", (body.username,))
    # 3) 密码错误 → 记录失败（可能触发锁定）
    if row is None or not verify_password(body.password, row["pass_hash"]):
        _record_login_fail(body.username)
        raise Unauthorized("用户名或密码错误")
    if row["disabled"]:
        raise Forbidden("账户已停用")
    # 4) 成功 → 清除失败计数
    _clear_login_fail(body.username)
    return {"token": create_jwt(row["id"], row["role"], settings),
            "user": {"id": row["id"], "username": row["username"],
                     "role": row["role"], "balance": row["balance"]}}
