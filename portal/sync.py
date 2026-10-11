"""portal/sync.py：任务同步循环 + 启动对账 + 充值单超时（Task-WWW.md §5.1、§9.4-2、§2.1、§6）。

数据流：
- main.py 注入 task_provider：无参 callable，返回 [dict]（TaskManager.list_full()），
  每项含 task_id/instance/workflow_name/status/created_at/finished_at/elapsed/error/
  outputs/params/user_token_hash（后两项仅同进程 provider 可见）。
- 本模块只依赖 portal.* + 该 dict 快照，**零 import core/server**；后台循环全部
  try/except 自守护，异常只记日志不抛出（§2.1 共享事件循环红线）。

归属与计费：
- freeze 在 precheck（提交时，billing.py）已扣余额 + active_count+1 + 记 freeze 流水。
- sync 只负责：建/推进 task_records，并在终态时调 settle（completed）/ refund（failed
  / cancelled）。匿名任务（无 token）从未 freeze，故只记录、不结算。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from portal.billing import refund, settle
from portal.config import PortalSettings
from portal.db import PortalDB, utcnow

logger = logging.getLogger("portal.sync")

TERMINAL = {"completed", "failed", "cancelled"}
_ACTIVE = ("pending", "running")


# ------------------------------------------------------------------ 时间工具
def _iso(epoch: Optional[float]) -> Optional[str]:
    """epoch 秒 → ISO8601 UTC（与 task_records 字段口径一致）。"""
    if not epoch:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _seconds_since(iso: str) -> float:
    """ISO8601 UTC（带 Z）→ 距今秒数。用 UTC 基准解析，避免 mktime 把 UTC
    字符串当本地时间造成 ±时区偏移（曾导致充值单刚建即被判超时作废）。"""
    try:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
    except (ValueError, OverflowError):
        return 0.0


# ------------------------------------------------------------------ 归属反查
async def _attribute(db: PortalDB, token_hash: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    """token_hash → (user_id, token_id)；停用/过期/未知 → (None, None)（匿名）。

    precheck 已在提交阶段拒掉停用 token，这里只做兜底（历史遗留/竞态）；
    取不到就按匿名记录（不结算，避免误扣）。
    """
    if not token_hash:
        return None, None
    row = await db.fetch_one(
        "SELECT u.id AS uid, u.disabled AS ud, t.id AS tid, t.disabled AS td,"
        " t.expires_at AS exp FROM user_tokens t JOIN users u ON u.id=t.user_id"
        " WHERE t.token_hash=?", (token_hash,))
    if row is None:
        return None, None
    if row["ud"] or row["td"]:
        return None, None
    if row["exp"] and row["exp"] < utcnow():
        return None, None
    return row["uid"], row["tid"]


# ------------------------------------------------------------------ 终态结算
async def _bill_terminal(db: PortalDB, settings: PortalSettings, view: dict,
                         user_id: Optional[int], token_id: Optional[int],
                         record_id: int) -> None:
    """终态计费：completed→settle；cancelled→refund(计费下限)；failed→refund(全额)。

    匿名（user_id None）无 freeze 可结算 → 直接跳过。settle/refund 自身幂等。
    """
    if user_id is None:
        return
    tid = view["task_id"]
    status = view["status"]
    params = view.get("params") or {}
    wf = view.get("workflow_name") or ""
    try:
        if status == "completed":
            charged = await settle(db, settings, task_id=tid, user_id=user_id,
                                   token_id=token_id, workflow_name=wf,
                                   actual_params=params)
        elif status == "cancelled":
            charged = await refund(db, settings, task_id=tid, user_id=user_id,
                                   token_id=token_id, reason="cancelled",
                                   workflow_name=wf,
                                   runtime_seconds=float(view.get("elapsed") or 0.0),
                                   full_params=params)
        else:  # failed（含超时-排队中）
            charged = await refund(db, settings, task_id=tid, user_id=user_id,
                                   token_id=token_id, reason="failed",
                                   workflow_name=wf, full_params=params)
        # 回写本次结算积分（/me"已使用/今日/本月消耗"数据源）
        await db.execute(
            "UPDATE task_records SET billable_credits=? WHERE id=?",
            (int(charged or 0), record_id))
    except Exception:
        logger.exception("[sync] 终态结算失败 task=%s status=%s（已吞掉）", tid, status)


# ------------------------------------------------------------------ 单任务
async def sync_task(db: PortalDB, settings: PortalSettings, view: dict) -> None:
    """单任务对账：无记录→建；终态→推进+结算；非终态→仅推进状态。幂等。"""
    tid = view["task_id"]
    status = view["status"]
    user_id, token_id = await _attribute(db, view.get("user_token_hash"))
    params_digest = json.dumps(view.get("params") or {}, ensure_ascii=False)
    outputs_json = json.dumps(
        [os.path.basename(p) for p in (view.get("outputs") or [])
         if isinstance(p, str)], ensure_ascii=False)
    duration = int(view.get("elapsed") or 0)
    error = view.get("error")

    ex = await db.fetch_one(
        "SELECT id, status FROM task_records WHERE mcp_task_id=?", (tid,))
    if ex is None:
        cur = await db.execute(
            "INSERT OR IGNORE INTO task_records(mcp_task_id, user_id, token_id,"
            " workflow_name, instance, params_digest, outputs, billable_credits,"
            " status, submitted_at, finished_at, duration_s, error)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tid, user_id, token_id, view.get("workflow_name"), view.get("instance"),
             params_digest, outputs_json, 0, status, _iso(view.get("created_at")),
             _iso(view.get("finished_at")), duration, error))
        if status in TERMINAL and cur.lastrowid:
            await _bill_terminal(db, settings, view, user_id, token_id, cur.lastrowid)
        return

    if ex["status"] in TERMINAL or ex["status"] == "lost":
        return  # 已结算/已对账，幂等
    if status in TERMINAL:
        await db.execute(
            "UPDATE task_records SET status=?, finished_at=?, duration_s=?, error=?,"
            " outputs=? WHERE id=?",
            (status, _iso(view.get("finished_at")), duration, error,
             outputs_json, ex["id"]))
        await _bill_terminal(db, settings, view, user_id, token_id, ex["id"])
    elif status != ex["status"]:
        await db.execute(
            "UPDATE task_records SET status=?, outputs=? WHERE id=?",
            (status, outputs_json, ex["id"]))


# ------------------------------------------------------------------ 丢失对账
async def _mark_lost(db: PortalDB, settings: PortalSettings, row: dict) -> None:
    tid = row["mcp_task_id"]
    await db.execute(
        "UPDATE task_records SET status='lost', finished_at=?,"
        " error='进程重启/内存裁剪：任务状态不可恢复，全额退款' WHERE id=?",
        (utcnow(), row["id"]))
    if row["user_id"] is not None:
        try:
            await refund(db, settings, task_id=tid, user_id=row["user_id"],
                         token_id=row["token_id"], reason="failed",
                         workflow_name=row.get("workflow_name") or "")
        except Exception:
            logger.exception("[对账] lost 退款失败 task=%s（已吞掉）", tid)
    await db.execute(
        "INSERT INTO admin_audit(admin_id, action, target, detail, created_at)"
        " VALUES(0,'lost_reconcile',?, '任务丢失对账+全额退款', ?)",
        (tid, utcnow()))
    logger.warning("[对账] task=%s 标 lost + 退款（user=%s token=%s）",
                  tid, row["user_id"], row["token_id"])


async def startup_reconcile(db: PortalDB, settings: PortalSettings,
                            provider: Callable[[], list[dict]]) -> None:
    """启动对账（§2.1）：进程重启丢内存任务表——把 DB 遗留的非终态任务 + 遗留
    freeze（无对应终态结算）标 lost + 退款 + 审计告警。

    两类来源都要覆盖：
    1) task_records 非终态，且该 task_id 已不在 provider（内存）里；
    2) credit_ledger 里的 freeze（ref_kind='task'）无 settle/refund、且非在途
       （含"提交即 freeze 后崩溃、task_records 都还没建"的孤儿 freeze）。
    在途（provider 里且非终态）的不动——正常结算。
    """
    present: dict[str, str] = {v["task_id"]: v["status"]
                               for v in (provider() or [])}

    def in_flight(task_id: str) -> bool:
        return task_id in present and present[task_id] not in TERMINAL

    # 1) 非终态 task_records
    rows = await db.fetch_all(
        "SELECT id, mcp_task_id, user_id, token_id, workflow_name FROM task_records"
        " WHERE status IN ('pending','running')")
    lost1 = 0
    for r in rows:
        if in_flight(r["mcp_task_id"]):
            continue
        await _mark_lost(db, settings, dict(r))
        lost1 += 1

    # 2) 孤儿 freeze（无终态结算、非在途）
    frz = await db.fetch_all(
        "SELECT ref_id, user_id, token_id FROM credit_ledger"
        " WHERE kind='freeze' AND ref_kind='task'")
    lost2 = 0
    for f in frz:
        tid = f["ref_id"]
        if in_flight(tid):
            continue
        settled = await db.scalar(
            "SELECT 1 FROM credit_ledger WHERE ref_kind='task' AND ref_id=?"
            " AND kind IN ('settle','refund')", (tid,))
        if settled:
            continue
        row = await db.fetch_one(
            "SELECT id, workflow_name, status FROM task_records WHERE mcp_task_id=?",
            (tid,))
        if row and row["status"] not in TERMINAL and row["status"] != "lost":
            await db.execute(
                "UPDATE task_records SET status='lost', finished_at=?,"
                " error='进程重启：在途任务丢失' WHERE id=?", (utcnow(), row["id"]))
        if f["user_id"] is not None:
            try:
                await refund(db, settings, task_id=tid, user_id=f["user_id"],
                             token_id=f["token_id"], reason="failed",
                             workflow_name=(row or {}).get("workflow_name") or "")
            except Exception:
                logger.exception("[对账] 孤儿 freeze 退款失败 task=%s", tid)
        await db.execute(
            "INSERT INTO admin_audit(admin_id, action, target, detail, created_at)"
            " VALUES(0,'lost_reconcile',?,'重启对账：在途 freeze 丢失+退款',?)",
            (tid, utcnow()))
        logger.warning("[对账] 重启遗留 task=%s 退款（user=%s）", tid, f["user_id"])
        lost2 += 1

    if lost1 or lost2:
        logger.warning("[对账] 启动对账完成：task_records %d + 孤儿 freeze %d 标 lost",
                       lost1, lost2)


# ------------------------------------------------------------------ 漏帧哨兵
# 内存 TaskManager 会裁剪终态任务（prune_terminal / _evict_locked）。若某任务在
# "变成终态"前就被裁掉，sync 永远读不到它的终态 → 余额/active 卡死。哨兵：连续
# 2 个 tick 在 provider 里消失的非终态 DB 记录 → 判 lost + 退款（§9.4-2）。
_absent_ticks: dict[str, int] = {}


async def _lost_sentinel(db: PortalDB, settings: PortalSettings,
                         present: set[str]) -> None:
    rows = await db.fetch_all(
        "SELECT id, mcp_task_id, user_id, token_id, workflow_name FROM task_records"
        " WHERE status IN ('pending','running')")
    current = set()
    for r in rows:
        current.add(r["mcp_task_id"])
        if r["mcp_task_id"] in present:
            _absent_ticks.pop(r["mcp_task_id"], None)
            continue
        n = _absent_ticks.get(r["mcp_task_id"], 0) + 1
        _absent_ticks[r["mcp_task_id"]] = n
        if n >= 2:
            await _mark_lost(db, settings, dict(r))
            _absent_ticks.pop(r["mcp_task_id"], None)
    for k in list(_absent_ticks):
        if k not in current:
            _absent_ticks.pop(k, None)


async def sync_once(db: PortalDB, settings: PortalSettings,
                    provider: Callable[[], list[dict]]) -> None:
    """一轮同步：对账全部 provider 任务 + 漏帧哨兵。单任务异常不拖累整轮。"""
    views = list(provider() or [])
    present = {v["task_id"] for v in views}
    for v in views:
        try:
            await sync_task(db, settings, v)
        except Exception:
            logger.exception("[sync] 处理任务 %s 异常（已吞掉）", v.get("task_id"))
    try:
        await _lost_sentinel(db, settings, present)
    except Exception:
        logger.exception("[sync] 漏帧哨兵异常（已吞掉）")


async def sync_loop(db: PortalDB, settings: PortalSettings,
                    provider: Callable[[], list[dict]],
                    interval: Optional[float] = None) -> None:
    """sync 主循环（自守护）：每 interval 秒跑一轮，异常只记日志不抛出。"""
    interval = settings.sync_interval_s if interval is None else interval
    logger.info("[sync] 循环启动，间隔 %ss", interval)
    while True:
        try:
            await sync_once(db, settings, provider)
        except Exception:
            logger.exception("[sync] 轮次异常（已吞掉，下轮重试）")
        await asyncio.sleep(interval)


# ------------------------------------------------------------------ 充值单超时
async def _expire_orders(db: PortalDB, settings: PortalSettings) -> int:
    rows = await db.fetch_all(
        "SELECT id, order_no, created_at FROM recharge_orders WHERE status='pending'")
    expired = 0
    for r in rows:
        if _seconds_since(r["created_at"]) > settings.order_timeout_s:
            await db.execute(
                "UPDATE recharge_orders SET status='cancelled' WHERE id=?", (r["id"],))
            expired += 1
    return expired


async def recharge_timeout_loop(db: PortalDB, settings: PortalSettings,
                                interval: float = 15.0) -> None:
    """充值单超时循环（自守护）：pending 超过 order_timeout_s 置 cancelled。"""
    logger.info("[recharge] 超时循环启动，间隔 %ss", interval)
    while True:
        try:
            n = await _expire_orders(db, settings)
            if n:
                logger.info("[recharge] 超时作废 %d 单", n)
        except Exception:
            logger.exception("[recharge] 超时循环异常（已吞掉）")
        await asyncio.sleep(interval)
