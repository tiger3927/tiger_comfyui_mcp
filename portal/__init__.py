"""门户包（Task-WWW.md）：多用户账户/积分/token/任务计费/模拟充值。

红线：本包内**零 import core/*、server/mcp_tools.py、server/rest_api.py**——
与 MCP 的唯一连接点是 main.py 组合时注入的 task_provider / precheck（dict/callable）。
"""
from portal.config import DEFAULT_RULES, PortalSettings  # noqa: F401
from portal.db import PortalDB  # noqa: F401

__all__ = ["PortalSettings", "PortalDB", "DEFAULT_RULES"]
