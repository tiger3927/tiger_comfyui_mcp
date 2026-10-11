"""建首个管理员账户（Task-WWW.md §6 认证 / §11 M1）。

用法（本地或服务器，conda base）：
    python scripts/seed_admin.py --username admin --password 'Secret#123' [--credits 100000]
    python scripts/seed_admin.py --config config.json --username root --password ...

密码可从环境变量 PORTAL_ADMIN_PASSWORD 提供（避免落 shell 历史）。
DB 路径默认取 config.json 的 portal.db_path。建号与授予积分均走 credit_ledger。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portal.accounts import create_user, grant_credits  # noqa: E402
from portal.config import PortalSettings  # noqa: E402
from portal.db import PortalDB, utcnow  # noqa: E402
from portal.errors import Conflict  # noqa: E402


async def run(args) -> int:
    cfg_path = Path(args.config)
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    portal_raw = raw.get("portal", {})
    settings = PortalSettings.from_dict(portal_raw)
    if args.db:
        settings.db_path = args.db
    # 相对路径按 config.json 所在目录解析
    if not Path(settings.db_path).is_absolute():
        settings.db_path = str(cfg_path.resolve().parent / settings.db_path)

    password = args.password or os.environ.get("PORTAL_ADMIN_PASSWORD", "")
    if not password:
        print("错误：需提供 --password 或环境变量 PORTAL_ADMIN_PASSWORD")
        return 2

    db = await PortalDB.open(settings)
    try:
        existing = await db.fetch_one("SELECT id, role FROM users WHERE username=?",
                                      (args.username,))
        if existing:
            uid = existing["id"]
            print(f"用户 {args.username!r} 已存在（id={uid}, role={existing['role']}），跳过建号")
        else:
            uid = await create_user(db, args.username, password, role="admin")
            print(f"已创建管理员 id={uid} username={args.username}（argon2 口令）")

        if args.credits > 0:
            # 幂等锚点：以运行时间戳为 ref，重复执行会再授予（故仅首次建议带 --credits）
            after = await grant_credits(
                db, user_id=uid, delta=args.credits, kind="seed",
                ref_kind="seed_admin", ref_id=f"{uid}:{utcnow()}",
                note="首管理员初始额度")
            print(f"已授予 {args.credits} 积分，当前余额 {after}")
        print("seed_admin 完成。")
        return 0
    finally:
        await db.close()


def main() -> int:
    p = argparse.ArgumentParser(description="门户首管理员初始化")
    p.add_argument("--config", default=str(Path(__file__).resolve().parent.parent / "config.json"))
    p.add_argument("--db", default=None, help="覆盖 DB 路径（默认取 config.portal.db_path）")
    p.add_argument("--username", required=True)
    p.add_argument("--password", default=None)
    p.add_argument("--credits", type=int, default=0, help="授予初始积分（0=不授）")
    args = p.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
