"""ComfyUI 配置数据源（Task-DB-Config §2.1）：Static / Db 双实现。

- StaticConfigProvider：读内存 ComfyUIConfig（config.json），行为与现状 100% 一致，
  兼作回归基准；门户未启用时 manager 的缺省 provider。
- DbConfigProvider：读 portal.db（comfyui_instances / instance_workflow_rules /
  workflow_whitelist + 四个 KV），带 3s TTL 缓存；管理端写操作完成后调用
  invalidate() 主动击穿，保证热更新即时生效。

InstanceRuntime 为轻量 dataclass（name/url/password/active/only/exclude）；
ComfyUIClient 仅消费 name/url/password，直接接受它。

fail-closed（§6）：查询异常（DB 锁死/表损坏）或组装后校验失败 → 抛
ConfigSystemError，消费侧拒绝新任务并打 ERROR 日志；不静默回退 Static
（避免配置漂移）。DB 恢复后下一次请求自动痊愈。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from schemas.models import ComfyUIConfig, RoutingWeights, WorkflowRules

logger = logging.getLogger(__name__)


class ConfigSystemError(Exception):
    """配置系统不可用（DB 查询异常或组装校验失败）——消费侧 fail-closed。"""


@dataclass
class InstanceRuntime:
    """单个实例的运行时视图（provider 统一返回结构）。"""

    name: str
    url: str
    password: str = ""
    active: bool = True
    workflow_rules: WorkflowRules = field(default_factory=WorkflowRules)


@dataclass(frozen=True)
class ConfigSnapshot:
    """一次组装 + 校验通过后的配置快照（不可变）。"""

    instances: list[InstanceRuntime]
    default_instance: str
    whitelist: list[str]
    prune_modes: dict[str, str]
    weights: RoutingWeights


def _normalize_url(url: str) -> str:
    """与 ComfyUIInstanceConfig._normalize_url 同源：strip + 去尾斜杠 + 非空。"""
    v = (url or "").strip().rstrip("/")
    if not v:
        raise ValueError("url 不能为空")
    return v


class ConfigProvider:
    """配置数据源协议（manager 只依赖五个读取 + invalidate）。"""

    async def get_instances(self) -> list[InstanceRuntime]:
        raise NotImplementedError

    async def get_default_instance(self) -> str:
        raise NotImplementedError

    async def get_whitelist(self) -> list[str]:
        raise NotImplementedError

    async def get_prune_modes(self) -> dict[str, str]:
        raise NotImplementedError

    async def get_routing_weights(self) -> RoutingWeights:
        raise NotImplementedError

    def invalidate(self) -> None:
        """主动失效缓存（DbConfigProvider 管理端写完调用；Static 无操作）。"""


class StaticConfigProvider(ConfigProvider):
    """读内存 ComfyUIConfig；行为与现状一致（回退/测试基准）。

    config.json 无"禁用实例"概念 → 全部 active=True（现状语义：配置里列出
    即可用）。
    """

    def __init__(self, config: ComfyUIConfig):
        self._config = config

    async def get_instances(self) -> list[InstanceRuntime]:
        return [
            InstanceRuntime(name=i.name, url=i.url, password=i.password,
                            active=True,
                            workflow_rules=WorkflowRules(
                                exclude=list(i.workflow_rules.exclude),
                                only=list(i.workflow_rules.only)))
            for i in self._config.comfyui_instances
        ]

    async def get_default_instance(self) -> str:
        return self._config.default_instance

    async def get_whitelist(self) -> list[str]:
        return list(self._config.allowed_workflows)

    async def get_prune_modes(self) -> dict[str, str]:
        return dict(self._config.workflow_prune_modes)

    async def get_routing_weights(self) -> RoutingWeights:
        return self._config.routing.weights


class DbConfigProvider(ConfigProvider):
    """读 portal.db；3s TTL 缓存仅为削减重复查询，非功能依赖。

    校验口径（§2.1，与启动时同源但略宽）：实例名非空唯一、url 归一化非空、
    default 在实例名列表内。注意：default 是否 active 是**写端点**校验
    （PUT /admin/comfyui/default）——若读端强制 active，禁用 default 实例会
    把全部新任务打成 fail-closed，违反"禁用随时可做"（§0-5）；读端只要求
    default 存在。
    """

    def __init__(self, db, ttl: float = 3.0):
        from portal.db import (COMFYUI_KV_DEFAULT, COMFYUI_KV_PRUNE_MODES,
                               COMFYUI_KV_ROUTING_PENDING,
                               COMFYUI_KV_ROUTING_RUNNING)
        self._db = db
        self._ttl = float(ttl)
        self._kv = {
            "default": COMFYUI_KV_DEFAULT,
            "pending": COMFYUI_KV_ROUTING_PENDING,
            "running": COMFYUI_KV_ROUTING_RUNNING,
            "prune": COMFYUI_KV_PRUNE_MODES,
        }
        self._cache: Optional[ConfigSnapshot] = None
        self._stamped: float = 0.0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    async def _snapshot(self) -> ConfigSnapshot:
        now = time.monotonic()
        if self._cache is not None and now - self._stamped < self._ttl:
            return self._cache
        async with self._lock:
            if self._cache is not None and \
                    time.monotonic() - self._stamped < self._ttl:
                return self._cache
            snap = await self._load_and_validate()
            self._cache = snap
            self._stamped = time.monotonic()
            return snap

    async def _load_and_validate(self) -> ConfigSnapshot:
        try:
            db = self._db
            inst_rows = await db.fetch_all(
                "SELECT id, name, url, password, active"
                " FROM comfyui_instances ORDER BY sort, id")
            rule_rows = await db.fetch_all(
                "SELECT instance_id, rule_type, pattern"
                " FROM instance_workflow_rules ORDER BY instance_id, id")
            wl_rows = await db.fetch_all(
                "SELECT pattern FROM workflow_whitelist WHERE active=1"
                " ORDER BY id")
            default = await db.get_setting(self._kv["default"])
            pending_raw = await db.get_setting(self._kv["pending"], "1.0")
            running_raw = await db.get_setting(self._kv["running"], "2.0")
            prune_raw = await db.get_setting(self._kv["prune"], "{}")

            instances: list[InstanceRuntime] = []
            for r in inst_rows:
                if not (r["name"] or "").strip():
                    raise ConfigSystemError("存在空实例名行")
                try:
                    url = _normalize_url(r["url"])
                except ValueError as e:
                    raise ConfigSystemError(
                        f"实例行 {r['name']!r} url 非法：{e}") from e
                inst = InstanceRuntime(
                    name=r["name"], url=url,
                    password=r["password"] or "", active=bool(r["active"]))
                for row in rule_rows:
                    if row["instance_id"] != r["id"]:
                        continue
                    pat = row["pattern"]
                    if row["rule_type"] == "exclude":
                        inst.workflow_rules.exclude.append(pat)
                    elif row["rule_type"] == "only":
                        inst.workflow_rules.only.append(pat)
                    else:
                        raise ConfigSystemError(
                            f"实例 {r['name']!r} 存在非法 rule_type "
                            f"{row['rule_type']!r}")
                instances.append(inst)
            if len({i.name for i in instances}) != len(instances):
                raise ConfigSystemError("实例名重复（DB 约束应阻止）")

            whitelist = [r["pattern"] for r in wl_rows]
            if default is None:
                raise ConfigSystemError("缺少 KV comfyui.default_instance")
            try:
                weights = RoutingWeights(
                    pending=float(pending_raw), running=float(running_raw))
            except Exception as e:
                raise ConfigSystemError(f"routing 权重非法：{e}") from e
            try:
                prune = json.loads(prune_raw or "{}")
            except Exception as e:
                raise ConfigSystemError(f"comfyui.prune_modes 非 JSON：{e}") from e
            if not isinstance(prune, dict):
                raise ConfigSystemError("comfyui.prune_modes 不是 JSON 对象")
            for k, mode in prune.items():
                if mode not in ("image_edit", "multi_ref"):
                    raise ConfigSystemError(
                        f"comfyui.prune_modes[{k!r}] 制度 {mode!r} 非法")
        except ConfigSystemError:
            raise
        except Exception as e:
            raise ConfigSystemError(f"portal.db 配置读取失败：{e}") from e

        if default not in {i.name for i in instances}:
            raise ConfigSystemError(f"default_instance={default!r} 不在实例列表中")
        return ConfigSnapshot(
            instances=instances,
            default_instance=default,
            whitelist=whitelist,
            prune_modes=prune,
            weights=weights,
        )

    def invalidate(self) -> None:
        self._cache = None
        self._stamped = 0.0

    # ------------------------------------------------------------------
    async def get_instances(self) -> list[InstanceRuntime]:
        return list((await self._snapshot()).instances)

    async def get_default_instance(self) -> str:
        return (await self._snapshot()).default_instance

    async def get_whitelist(self) -> list[str]:
        return list((await self._snapshot()).whitelist)

    async def get_prune_modes(self) -> dict[str, str]:
        return dict((await self._snapshot()).prune_modes)

    async def get_routing_weights(self) -> RoutingWeights:
        return (await self._snapshot()).weights
