"""我的任务历史：/me/tasks（只列输出文件名，不渲染/不下载，Task-WWW.md §6）。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request

from portal.security import get_current_user

router = APIRouter(tags=["tasks"])


@router.get("/me/tasks")
async def my_tasks(request: Request, page: int = 1, size: int = 20,
                   user: dict = Depends(get_current_user)):
    db = request.app.state.db
    page = max(1, page)
    size = min(200, max(1, size))
    total = await db.scalar(
        "SELECT COUNT(*) FROM task_records WHERE user_id=?", (user["id"],), default=0)
    rows = await db.fetch_all(
        "SELECT mcp_task_id, workflow_name, instance, status, billable_credits,"
        " outputs, submitted_at, finished_at, duration_s, error FROM task_records"
        " WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
        (user["id"], size, (page - 1) * size))
    items = []
    for r in rows:
        d = dict(r)
        try:
            d["outputs"] = json.loads(d["outputs"]) if d["outputs"] else []
        except (ValueError, TypeError):
            d["outputs"] = []
        items.append(d)
    return {"total": total, "page": page, "size": size, "items": items}
