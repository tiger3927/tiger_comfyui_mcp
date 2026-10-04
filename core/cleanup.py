"""cleanup：output/ 过期文件清理 + 任务表裁剪 + 周期后台任务（D14）。

- 启动时立即跑一轮，之后每 cleanup_interval_hours 跑一轮（≤0 仅启动一次）。
- 文件删除经线程池（asyncio.to_thread）执行，不阻塞事件循环。
- 任何异常只记日志，不影响主服务。
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from core.tasks import TaskManager

logger = logging.getLogger(__name__)


def cleanup_output_files(output_dir: Path | str, retention_days: float) -> int:
    """按 mtime 删除 output_dir 内（含子目录）超过 retention_days 的文件。

    retention_days ≤ 0 或目录不存在时不做任何事。返回删除文件数。
    """
    if retention_days <= 0:
        return 0
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        return 0
    cutoff = time.time() - retention_days * 86400
    # 第一遍：删过期文件
    removed = 0
    for p in output_dir.rglob("*"):
        try:
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
                logger.info("[cleanup] 删除过期产物 %s", p.name)
        except OSError as e:
            logger.warning("[cleanup] 处理 %s 失败：%s", p, e)
    # 第二遍：清空子目录（深度从深到浅，父目录可能因文件删除变空）
    dirs = [p for p in output_dir.rglob("*") if p.is_dir()]
    for d in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        try:
            if not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass
    if removed:
        logger.info("[cleanup] output/ 过期清理完成：删 %d 个文件", removed)
    return removed


def prune_tasks(task_manager: TaskManager,
                task_retention_hours: float,
                task_max_retained: int) -> int:
    """裁剪终态任务，返回删除条数。"""
    return task_manager.prune_terminal(task_retention_hours, task_max_retained)


async def run_cleanup_once(output_dir: Path | str,
                           retention_days: float,
                           task_manager: Optional[TaskManager] = None,
                           task_retention_hours: float = 0.0,
                           task_max_retained: int = 0) -> dict:
    """跑一轮清理，返回 {"removed_files": n, "removed_tasks": m}。"""
    removed_files = await asyncio.to_thread(cleanup_output_files,
                                            output_dir, retention_days)
    removed_tasks = 0
    if task_manager is not None:
        removed_tasks = await asyncio.to_thread(
            task_manager.prune_terminal, task_retention_hours, task_max_retained)
    return {"removed_files": removed_files, "removed_tasks": removed_tasks}


async def start_cleanup_loop(output_dir: Path | str,
                             retention_days: float,
                             interval_hours: float,
                             task_manager: Optional[TaskManager] = None,
                             task_retention_hours: float = 0.0,
                             task_max_retained: int = 0) -> None:
    """后台清理循环：启动即跑一次；interval_hours > 0 时周期执行。

    由 main.py lifespan 以 create_task 启动，退出时 cancel。
    """
    while True:
        try:
            stats = await run_cleanup_once(output_dir, retention_days,
                                           task_manager, task_retention_hours,
                                           task_max_retained)
            if stats["removed_files"] or stats["removed_tasks"]:
                logger.info("[cleanup] 本轮清理：文件 %d / 任务 %d",
                            stats["removed_files"], stats["removed_tasks"])
        except Exception:
            logger.exception("[cleanup] 清理任务异常（不影响主服务，下轮继续）")
        if interval_hours <= 0:
            break
        await asyncio.sleep(interval_hours * 3600)
