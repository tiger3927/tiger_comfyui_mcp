"""门户 REST 路由（Task-WWW.md §6）。前缀 /portal/api 由 main.py 挂载；
各路由用绝对路径（不叠 router prefix），鉴权走 portal.security 依赖。"""
from portal.routers import admin, auth, me, pay, recharges, tasks, tokens  # noqa: F401

__all__ = ["auth", "me", "tokens", "tasks", "recharges", "pay", "admin"]
