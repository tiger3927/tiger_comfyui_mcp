"""门户统一异常：携带 code/http_status，REST 层据此渲染 {error:{code,message}}。

门户包红线：本包内不 import core/* 与 server/*（见 Task-WWW.md §2.1）。
"""
from __future__ import annotations


class PortalError(Exception):
    code = "internal"
    http_status = 500

    def __init__(self, message: str = "", *, code: str | None = None):
        super().__init__(message or self.__class__.__doc__ or self.code)
        self.message = message or self.code
        if code:
            self.code = code

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


class BadRequest(PortalError):
    code = "bad_request"
    http_status = 400


class Unauthorized(PortalError):
    code = "unauthorized"
    http_status = 401


class InvalidToken(PortalError):
    code = "invalid_token"
    http_status = 401


class Forbidden(PortalError):
    code = "forbidden"
    http_status = 403


class AnonymousBlocked(PortalError):
    """allow_anonymous=0 时，未带 user token 的提交被拒（§5.1-3）。"""

    code = "anonymous_blocked"
    http_status = 403


class NotFound(PortalError):
    code = "not_found"
    http_status = 404


class InsufficientCredits(PortalError):
    code = "insufficient_credits"
    http_status = 402


class TokenLimitExceeded(PortalError):
    code = "token_limit_exceeded"
    http_status = 403


class ActiveLimitExceeded(PortalError):
    """每用户在途任务数超限（§9.4-3）。"""

    code = "active_limit_exceeded"
    http_status = 429


class Conflict(PortalError):
    code = "conflict"
    http_status = 409
