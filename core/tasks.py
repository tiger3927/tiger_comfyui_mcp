"""tasks：内存任务状态机（单进程，无 Redis）。

状态：pending（未提交/排队）-> running -> completed / failed / cancelled。
进度回调异常一律吞掉，不影响主执行流。
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from schemas.models import TaskStatus

logger = logging.getLogger(__name__)


def _fmt_ts(ts: Optional[float]) -> Optional[str]:
    """epoch → 本地时间可读串（AI 面向输出，避免裸时间戳占 token）。"""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else None


@dataclass
class TaskRecord:
    task_id: str
    instance: str
    workflow_name: str
    status: TaskStatus = TaskStatus.PENDING
    prompt_id: Optional[str] = None
    progress_nodes: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    text_outputs: dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None
    elapsed: float = 0.0
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "instance": self.instance,
            "workflow_name": self.workflow_name,
            "status": self.status.value,
            "prompt_id": self.prompt_id,
            "progress_nodes": list(self.progress_nodes),
            "outputs": list(self.outputs),
            "text_outputs": dict(self.text_outputs),
            "error": self.error,
            "elapsed": self.elapsed,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class TaskManager:
    def __init__(self, max_records: int = 200):
        self._tasks: dict[str, TaskRecord] = {}
        self._jobs: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._max_records = max_records

    async def create(self, instance: str, workflow_name: str) -> TaskRecord:
        async with self._lock:
            record = TaskRecord(
                task_id=uuid.uuid4().hex[:12],
                instance=instance,
                workflow_name=workflow_name,
            )
            self._tasks[record.task_id] = record
            self._evict_locked()
            return record

    async def attach_job(self, task_id: str, job: asyncio.Task) -> None:
        async with self._lock:
            self._jobs[task_id] = job

    def get(self, task_id: str) -> Optional[TaskRecord]:
        return self._tasks.get(task_id)

    def list(self) -> list[dict]:
        return sorted((t.to_dict() for t in self._tasks.values()),
                      key=lambda d: d["created_at"], reverse=True)

    def has_active(self, instance: str) -> bool:
        return any(t.instance == instance and t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
                   for t in self._tasks.values())

    def get_job(self, task_id: str) -> Optional[asyncio.Task]:
        return self._jobs.get(task_id)

    async def update_progress(self, task_id: str, node_id: Optional[str]) -> None:
        t = self._tasks.get(task_id)
        if not t:
            return
        if t.status == TaskStatus.PENDING:
            t.status = TaskStatus.RUNNING
        if node_id and node_id not in t.progress_nodes:
            t.progress_nodes.append(node_id)

    async def finish(self, task_id: str, status: TaskStatus,
                     prompt_id: Optional[str] = None,
                     outputs: Optional[list[str]] = None,
                     text_outputs: Optional[dict[str, str]] = None,
                     error: Optional[str] = None,
                     elapsed: float = 0.0) -> None:
        t = self._tasks.get(task_id)
        if not t:
            return
        t.status = status
        t.prompt_id = prompt_id or t.prompt_id
        t.outputs = list(outputs or [])
        t.text_outputs = dict(text_outputs or {})
        t.error = error
        t.elapsed = elapsed
        t.finished_at = time.time()
        self._jobs.pop(task_id, None)
        logger.info("[tasks] %s -> %s%s", task_id, status.value,
                    f"（{error}）" if error else "")

    async def cancel_job(self, task_id: str) -> bool:
        """pending 阶段直接取消 asyncio job。"""
        job = self._jobs.get(task_id)
        if job and not job.done():
            job.cancel()
            return True
        return False

    def workflow_stats(self, workflow_name: str, fail_limit: int = 5) -> dict:
        """P5.8/P5.8.1：按 workflow_name 聚合任务（仅本进程内存记录：重启清零、受 D14 裁剪）。

        给 AI 避坑用：success_rate=completed/total（无终态为 None，保留 4 位）；
        recent_failures 按最晚优先取至多 fail_limit 类失败 error（取消非失败），
        同类去重合并（count + 最近一次出现时间），error 截断 300 字符，时间用本地可读串。
        """
        all_recs = list(self._tasks.values())
        finished = [t for t in all_recs
                    if t.workflow_name == workflow_name and t.finished_at is not None]
        finished.sort(key=lambda t: t.finished_at or 0, reverse=True)
        total = len(finished)
        completed = sum(1 for t in finished if t.status == TaskStatus.COMPLETED)
        recent: list[dict] = []
        for t in finished:  # 已按最晚优先；取消非失败
            if t.status != TaskStatus.FAILED or not t.error:
                continue
            err = t.error.strip()
            if len(err) > 300:
                err = err[:300] + "..."
            for e in recent:
                if e["error"] == err:
                    e["count"] += 1
                    break
            else:  # 首个遇到的即最近一次出现
                recent.append({"error": err, "count": 1,
                               "last_at": _fmt_ts(t.finished_at)})
                if len(recent) == fail_limit:
                    break
        return {
            "total": total,
            "completed": completed,
            "failed": sum(1 for t in finished if t.status == TaskStatus.FAILED),
            "cancelled": sum(1 for t in finished if t.status == TaskStatus.CANCELLED),
            "success_rate": round(completed / total, 4) if total else None,
            "in_progress": sum(1 for t in all_recs
                               if t.workflow_name == workflow_name
                               and t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)),
            "last_finished_at": _fmt_ts(finished[0].finished_at) if finished else None,
            "recent_failures": recent,
        }

    def prune_terminal(self, max_age_hours: float, max_terminal: int) -> int:
        """裁剪终态任务（D14）：finished_at 超过 max_age_hours 的按最老优先删，
        再对剩余终态按数量保留最近 max_terminal 条。active（pending/running）永不删。
        返回删除条数。两参数均 ≤0 时直接返回 0。"""
        if max_age_hours <= 0 and max_terminal <= 0:
            return 0
        now = time.time()
        removed = 0
        if max_age_hours > 0:
            expired = [t for t in self._tasks.values()
                       if t.finished_at is not None
                       and now - t.finished_at > max_age_hours * 3600]
            for t in sorted(expired, key=lambda t: t.finished_at or 0):
                self._tasks.pop(t.task_id, None)
                self._jobs.pop(t.task_id, None)
                removed += 1
        if max_terminal > 0:
            finished = [t for t in self._tasks.values() if t.finished_at is not None]
            finished.sort(key=lambda t: t.finished_at or 0, reverse=True)
            for t in finished[max_terminal:]:
                self._tasks.pop(t.task_id, None)
                self._jobs.pop(t.task_id, None)
                removed += 1
        if removed:
            logger.info("[tasks] 裁剪终态任务 %d 条（现余 %d）", removed, len(self._tasks))
        return removed

    def _evict_locked(self) -> None:
        if len(self._tasks) <= self._max_records:
            return
        finished = [t for t in self._tasks.values() if t.finished_at is not None]
        finished.sort(key=lambda t: t.finished_at or 0)
        overflow = len(self._tasks) - self._max_records
        for t in finished[:overflow]:
            self._tasks.pop(t.task_id, None)
