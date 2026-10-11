"""Token 管理：/me/tokens CRUD（明文仅创建时返回一次，Task-WWW.md §6、§3.3）。"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from portal.accounts import create_token, token_remaining
from portal.errors import BadRequest, NotFound
from portal.security import get_current_user

router = APIRouter(tags=["tokens"])

_TOKEN_COLS = ("id, name, token_prefix, token_plain, credit_limit, used, expires_at, disabled,"
               " created_at")


@router.get("/me/tokens")
async def my_tokens(request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    rows = await db.fetch_all(
        f"SELECT {_TOKEN_COLS} FROM user_tokens WHERE user_id=? ORDER BY id",
        (user["id"],))
    out = []
    for r in rows:
        d = dict(r)
        d["remaining"] = await token_remaining(db, r["id"])
        out.append(d)
    return {"tokens": out}


class TokenIn(BaseModel):
    name: str
    credit_limit: int = 0
    expires_at: Optional[str] = None


@router.post("/me/tokens")
async def create_my_token(request: Request, body: TokenIn,
                          user: dict = Depends(get_current_user)):
    db = request.app.state.db
    if body.credit_limit < 0:
        raise BadRequest("credit_limit 不能为负")
    tid, plain = await create_token(db, user["id"], body.name,
                                    credit_limit=body.credit_limit,
                                    expires_at=body.expires_at)
    return {"id": tid, "name": body.name, "token_prefix": plain[:10],
            "credit_limit": body.credit_limit, "token": plain}


class TokenPatch(BaseModel):
    credit_limit: Optional[int] = None
    disabled: Optional[int] = None


@router.patch("/me/tokens/{tid}")
async def update_my_token(request: Request, tid: int, body: TokenPatch,
                          user: dict = Depends(get_current_user)):
    db = request.app.state.db
    row = await db.fetch_one(
        "SELECT id FROM user_tokens WHERE id=? AND user_id=?", (tid, user["id"]))
    if row is None:
        raise NotFound("token 不存在")
    if body.credit_limit is not None:
        if body.credit_limit < 0:
            raise BadRequest("credit_limit 不能为负")
        await db.execute("UPDATE user_tokens SET credit_limit=? WHERE id=?",
                         (body.credit_limit, tid))
    if body.disabled is not None:
        await db.execute("UPDATE user_tokens SET disabled=? WHERE id=?",
                         (1 if body.disabled else 0, tid))
    return {"ok": True}


@router.delete("/me/tokens/{tid}")
async def delete_my_token(request: Request, tid: int,
                          user: dict = Depends(get_current_user)):
    db = request.app.state.db
    row = await db.fetch_one(
        "SELECT id FROM user_tokens WHERE id=? AND user_id=?", (tid, user["id"]))
    if row is None:
        raise NotFound("token 不存在")
    # 近 7 天有任务则禁删（防丢账，§6）
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                           time.gmtime(time.time() - 7 * 86400))
    recent = await db.scalar(
        "SELECT COUNT(*) FROM task_records WHERE token_id=? AND submitted_at>=?",
        (tid, cutoff))
    if recent:
        raise BadRequest("该 token 近 7 天内有任务，不能删除（防丢账）")
    await db.execute("DELETE FROM user_tokens WHERE id=?", (tid,))
    return {"ok": True}
