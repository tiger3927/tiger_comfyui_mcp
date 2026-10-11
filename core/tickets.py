"""一次性上传票据（媒体上传通道 REST 化的桥梁）。

背景：MCP 层不再提供上传工具（comfyui_upload_file 已移除）——媒体文件一律
REST POST /api/upload multipart 直传（字节走 HTTP，不进模型上下文）。
票据是无 key MCP agent 的桥梁：

- 由 MCP 只读工具 comfyui_request_upload_ticket 签发（AuthMiddleware 只读豁免，
  无 key 可调；签发仅写内存态，无持久副作用）
- 绑定 instance + file_type，短时效（默认 300s）、单次有效
- /api/upload 凭票据免 Bearer——权限被限定为"传一个文件到绑定的实例"，
  不含用户身份/积分/submit 权限（权限最小化）

票据即使用随报错/工具返回进入对话历史也无泄露价值：短命、单次、无身份。
"""
from __future__ import annotations

import logging
import secrets
import threading
import time

logger = logging.getLogger(__name__)

# 签发限流窗口（每 IP 滑动窗口，秒）
_ISSUE_WINDOW_S = 600.0


class TicketStore:
    """线程安全的内存票据表；进程重启即清零（票据本就短命，无需持久化）。"""

    def __init__(self, ttl_seconds: float = 300.0,
                 max_per_ip: int = 10, max_active: int = 200):
        self.ttl_seconds = float(ttl_seconds)
        self.max_per_ip = int(max_per_ip)
        self.max_active = int(max_active)
        self._lock = threading.Lock()
        # ticket -> {"instance", "file_type", "exp", "used", "ip"}
        self._tickets: dict[str, dict] = {}
        # ip -> [签发时间戳, ...]（滑动窗口限流）
        self._ip_issues: dict[str, list[float]] = {}

    # -- 签发 ------------------------------------------------------------
    def issue(self, instance: str, file_type: str = "input",
              ip: str = "") -> dict:
        """签发票据。超限抛 PermissionError（调用方转为 4xx/错误消息）。

        返回 {"ticket", "instance", "file_type", "expires_in"}。
        """
        now = time.time()
        with self._lock:
            self._sweep_locked(now)
            if ip:
                window = [t for t in self._ip_issues.get(ip, [])
                          if now - t < _ISSUE_WINDOW_S]
                if len(window) >= self.max_per_ip:
                    raise PermissionError(
                        f"票据签发过于频繁（每 IP {_ISSUE_WINDOW_S / 60:.0f} 分钟"
                        f"上限 {self.max_per_ip} 张），请稍后再试")
                window.append(now)
                self._ip_issues[ip] = window
            active = sum(1 for t in self._tickets.values()
                         if not t["used"] and now <= t["exp"])
            if active >= self.max_active:
                raise PermissionError(
                    f"在途票据已达上限（{self.max_active}），请稍后再试")
            ticket = "up_" + secrets.token_urlsafe(24)
            self._tickets[ticket] = {
                "instance": instance, "file_type": file_type,
                "exp": now + self.ttl_seconds, "used": False, "ip": ip,
            }
        logger.info("[ticket] 签发 %s…：instance=%s file_type=%s ttl=%ss ip=%s",
                    ticket[:8], instance, file_type,
                    int(self.ttl_seconds), ip or "-")
        return {"ticket": ticket, "instance": instance,
                "file_type": file_type, "expires_in": int(self.ttl_seconds)}

    # -- 核销 ------------------------------------------------------------
    def consume(self, ticket: str, instance: str,
                file_type: str = "input") -> tuple[bool, str]:
        """校验并核销票据。返回 (ok, 错误消息)；ok=True 时票据已标记 used。"""
        with self._lock:
            self._sweep_locked(time.time())
            info = self._tickets.get(ticket)
            if info is None:
                return False, "上传票据无效"
            if info["used"]:
                return False, "上传票据已被使用（单次有效）"
            if time.time() > info["exp"]:
                return False, "上传票据已过期"
            if info["instance"] != instance:
                return False, (f"上传票据绑定实例 {info['instance']!r}，"
                               f"与请求实例 {instance!r} 不符")
            if info["file_type"] != file_type:
                return False, (f"上传票据绑定 file_type={info['file_type']!r}，"
                               f"与请求 file_type={file_type!r} 不符")
            info["used"] = True
        logger.info("[ticket] 核销 %s…：instance=%s file_type=%s",
                    ticket[:8], instance, file_type)
        return True, ""

    # -- 内部 ------------------------------------------------------------
    def _sweep_locked(self, now: float, grace: float = 3600.0) -> None:
        """清票据与 IP 窗口。

        - used 的票据：exp 一过即删（复用价值为零）
        - 过期未用：保留 grace 秒再删——保证窗口期内核销时报准确的"已过期"
          而非笼统的"无效"；过宽限期后才清出内存
        """
        dead = [k for k, v in self._tickets.items()
                if (v["used"] and now > v["exp"]) or now > v["exp"] + grace]
        for k in dead:
            self._tickets.pop(k, None)
        for ip in list(self._ip_issues):
            self._ip_issues[ip] = [
                t for t in self._ip_issues[ip] if now - t < _ISSUE_WINDOW_S]
            if not self._ip_issues[ip]:
                self._ip_issues.pop(ip, None)

    def active_count(self) -> int:
        with self._lock:
            self._sweep_locked(time.time())
            now = time.time()
            return sum(1 for v in self._tickets.values()
                       if not v["used"] and now <= v["exp"])
