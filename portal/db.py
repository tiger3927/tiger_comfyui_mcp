"""门户 DB 层：aiosqlite 单连接（WAL）+ §4 建表 DDL + PRAGMA 基线 + 事务。

红线（§2.1）：门户与 MCP 同进程共享事件循环——一律 aiosqlite（查询跑后台线程），
禁阻塞；写者单逻辑来源，用 asyncio.Lock 串行化事务即可（WAL 下读者不挡写者）。
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from portal.config import DEFAULT_RULES, PortalSettings

logger = logging.getLogger("portal.db")

# PRAGMA 基线（§9.3）
_PRAGMAS = (
    "journal_mode=WAL",
    "synchronous=NORMAL",
    "busy_timeout=5000",
    "cache_size=-8000",
    "mmap_size=134217728",
    "foreign_keys=ON",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY,
  username      TEXT UNIQUE NOT NULL,
  pass_hash     TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT 'user',
  balance       INTEGER NOT NULL DEFAULT 0,
  active_count  INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL,
  disabled      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_tokens (
  id             INTEGER PRIMARY KEY,
  user_id        INTEGER NOT NULL REFERENCES users(id),
  name           TEXT NOT NULL,
  token_hash     TEXT UNIQUE NOT NULL,
  token_prefix   TEXT NOT NULL,
  token_plain    TEXT,
  credit_limit   INTEGER NOT NULL DEFAULT 0,
  used           INTEGER NOT NULL DEFAULT 0,
  expires_at     TEXT,
  disabled       INTEGER NOT NULL DEFAULT 0,
  created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS credit_rules (
  id             INTEGER PRIMARY KEY,
  pattern        TEXT NOT NULL,
  media          TEXT NOT NULL,
  price_per_mp   REAL NOT NULL DEFAULT 0,
  price_per_char REAL NOT NULL DEFAULT 0,
  flat_price     INTEGER NOT NULL DEFAULT 0,
  fps            INTEGER NOT NULL DEFAULT 0,
  width_param    TEXT, height_param TEXT,
  seconds_param  TEXT,
  char_param     TEXT,
  default_width  INTEGER, default_height INTEGER,
  active         INTEGER NOT NULL DEFAULT 1,
  remark         TEXT NOT NULL DEFAULT '',
  updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recharge_orders (
  id            INTEGER PRIMARY KEY,
  order_no      TEXT UNIQUE NOT NULL,
  user_id       INTEGER NOT NULL REFERENCES users(id),
  amount_rmb    INTEGER NOT NULL,
  credits       INTEGER NOT NULL,
  status        TEXT NOT NULL DEFAULT 'pending',
  qr_url        TEXT NOT NULL,
  paid_at       TEXT,
  credited_at   TEXT,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_records (
  id             INTEGER PRIMARY KEY,
  mcp_task_id    TEXT UNIQUE NOT NULL,
  user_id        INTEGER REFERENCES users(id),
  token_id       INTEGER REFERENCES user_tokens(id),
  workflow_name  TEXT NOT NULL,
  instance       TEXT,
  params_digest  TEXT,
  outputs        TEXT,             -- 输出文件名清单（JSON 数组，只存名字，不渲染/不下载）
  billable_credits INTEGER NOT NULL DEFAULT 0,
  status         TEXT NOT NULL,
  submitted_at   TEXT NOT NULL,
  finished_at    TEXT,
  duration_s     INTEGER,
  error          TEXT
);

CREATE TABLE IF NOT EXISTS credit_ledger (
  id           INTEGER PRIMARY KEY,
  user_id      INTEGER NOT NULL REFERENCES users(id),
  token_id     INTEGER REFERENCES user_tokens(id),
  delta        INTEGER NOT NULL,
  kind         TEXT NOT NULL,
  ref_kind     TEXT NOT NULL,
  ref_id       TEXT,
  balance_after INTEGER NOT NULL,
  note         TEXT,
  created_at   TEXT NOT NULL,
  UNIQUE (kind, ref_kind, ref_id)
);

CREATE TABLE IF NOT EXISTS admin_audit (
  id INTEGER PRIMARY KEY,
  admin_id INTEGER NOT NULL,
  action TEXT NOT NULL,
  target TEXT, detail TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT NOT NULL);

CREATE INDEX IF NOT EXISTS idx_task_user ON task_records(user_id, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_ledger_user ON credit_ledger(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_token_user ON user_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_order_user ON recharge_orders(user_id, created_at DESC);
"""

_DEFAULT_SETTINGS = {
    "allow_anonymous": "1",     # 内测放行匿名；公网改 0（§5.1-3）
    "registration_open": "1",   # 注册开关（§8-7）
    "new_user_bonus_credits": "10000",  # 新用户注册赠送积分（0=不赠送）
}


def utcnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class PortalDB:
    """单 aiosqlite 连接封装；写事务经 transaction() 串行化（读者不受影响）。"""

    def __init__(self, path: str | Path, conn: aiosqlite.Connection):
        self._path = str(path)
        self._conn = conn
        self._lock = asyncio.Lock()

    # ---------------------------------------------------------------- open
    @classmethod
    async def open(cls, settings: PortalSettings) -> "PortalDB":
        p = Path(settings.db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(str(p), isolation_level=None,
                                       check_same_thread=False)
        conn.row_factory = aiosqlite.Row
        for pr in _PRAGMAS:
            await conn.execute(f"PRAGMA {pr}")
        db = cls(p, conn)
        await db._bootstrap()
        logger.info("portal.db 就绪：%s（WAL / synchronous=NORMAL）", p)
        return db

    async def _bootstrap(self) -> None:
        await self._conn.executescript(_SCHEMA)
        await self._migrate()
        # settings 播种（缺失才插，不覆盖管理员改过的值）
        for k, v in _DEFAULT_SETTINGS.items():
            await self._conn.execute(
                "INSERT OR IGNORE INTO settings(k, v) VALUES(?, ?)", (k, v))
        # credit_rules 播种（表空时才灌种子）
        row = await self._conn.execute_fetchall("SELECT COUNT(*) AS c FROM credit_rules")
        if row and row[0]["c"] == 0:
            now = utcnow()
            for r in DEFAULT_RULES:
                await self._conn.execute(
                    "INSERT INTO credit_rules(pattern, media, price_per_mp, price_per_char,"
                    " flat_price, fps, width_param, height_param, seconds_param, char_param,"
                    " default_width, default_height, active, remark, updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
                    (r.pattern, r.media, r.price_per_mp, r.price_per_char, r.flat_price,
                     r.fps, r.width_param, r.height_param, r.seconds_param, r.char_param,
                     r.default_width, r.default_height, r.remark, now))
            logger.info("credit_rules 播种 %d 条", len(DEFAULT_RULES))

    async def _migrate(self) -> None:
        """旧表加列（CREATE TABLE IF NOT EXISTS 不给已存在的表补新列）。幂等。"""
        cols = await self._conn.execute_fetchall("PRAGMA table_info(user_tokens)")
        if "token_plain" not in {c["name"] for c in cols}:
            await self._conn.execute("ALTER TABLE user_tokens ADD COLUMN token_plain TEXT")
            logger.info("schema 迁移：user_tokens + token_plain")

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    @property
    def conn(self) -> aiosqlite.Connection:
        return self._conn

    # --------------------------------------------------------------- helpers
    async def fetch_one(self, sql: str, params: tuple[Any, ...] = ()):
        cur = await self._conn.execute(sql, params)
        row = await cur.fetchone()
        await cur.close()
        return row

    async def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list:
        cur = await self._conn.execute(sql, params)
        rows = await cur.fetchall()
        await cur.close()
        return list(rows)

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        return await self._conn.execute(sql, params)

    async def scalar(self, sql: str, params: tuple[Any, ...] = (), default: Any = None):
        row = await self.fetch_one(sql, params)
        if row is None:
            return default
        return row[0]

    async def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = await self.fetch_one("SELECT v FROM settings WHERE k=?", (key,))
        return row["v"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self._conn.execute(
            "INSERT INTO settings(k, v) VALUES(?, ?)"
            " ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, value))

    # ------------------------------------------------------------ transaction
    @asynccontextmanager
    async def transaction(self):
        """BEGIN IMMEDIATE：占写锁，保证校验+写入原子（§2.1 precheck/freeze 同事务）。

        事务内用 `async with db.transaction() as tx:`，tx 即连接本身，调用
        tx.execute(...)；异常自动 ROLLBACK，正常退出 COMMIT。串行化由 self._lock 兜底。
        """
        await self._lock.acquire()
        try:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                await self._conn.execute("COMMIT")
            except Exception:
                await self._conn.execute("ROLLBACK")
                raise
        finally:
            self._lock.release()
