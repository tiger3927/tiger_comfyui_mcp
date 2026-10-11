"""scripts/reconcile.py：门户积分对账（Task-WWW.md §2.1、§14.6）。

**服务停止时**手动跑：把 portal.db 里遗留的非终态任务 + 孤儿 freeze 标 lost +
全额退款（复用 portal.sync.startup_reconcile；provider 返回空 = 无在途任务）。

用法：
  python scripts/reconcile.py                # DRY-RUN：只报告不写库（默认）
  python scripts/reconcile.py --apply        # 真正写库（对账+退款）
  python scripts/reconcile.py --config path  # 指定 config（取 portal 段 settings）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from portal.config import PortalSettings  # noqa: E402
from portal.db import PortalDB  # noqa: E402
from portal.sync import startup_reconcile  # noqa: E402


def _settings(cfg_path: Path) -> PortalSettings:
    raw = (json.loads(cfg_path.read_text(encoding="utf-8"))
           if cfg_path.exists() else {})
    return PortalSettings.from_dict(raw.get("portal") or {})


async def _report(db: PortalDB) -> None:
    active = await db.scalar(
        "SELECT COUNT(*) FROM task_records WHERE status IN ('pending','running')")
    orphan = await db.scalar(
        "SELECT COUNT(*) FROM credit_ledger WHERE kind='freeze' AND ref_kind='task'"
        " AND ref_id NOT IN (SELECT ref_id FROM credit_ledger"
        "   WHERE ref_kind='task' AND kind IN ('settle','refund'))")
    lost = await db.scalar(
        "SELECT COUNT(*) FROM task_records WHERE status='lost'")
    print(f"[reconcile] 非终态任务={active}  未结算孤儿 freeze={orphan}"
          f"  已 lost 记录={lost}")


async def main() -> None:
    ap = argparse.ArgumentParser(description="门户积分对账（服务停止时跑）")
    ap.add_argument("--config", default=str(PROJECT_ROOT / "config.json"))
    ap.add_argument("--apply", action="store_true", help="真正写库（对账+退款）")
    args = ap.parse_args()

    settings = _settings(Path(args.config))
    db = await PortalDB.open(settings)
    try:
        if args.apply:
            await _report(db)
            await startup_reconcile(db, settings, provider=lambda: [])
            print("[reconcile] 对账完成：")
            await _report(db)
        else:
            print("[reconcile] DRY-RUN（只报告不写库；--apply 才生效）")
            await _report(db)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
