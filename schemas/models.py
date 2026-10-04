"""Pydantic 模型：配置、任务状态、工作流参数、执行结果。"""
from __future__ import annotations

import enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkflowRules(BaseModel):
    """实例的工作流匹配规则（P5.13）。评估顺序固定：exclude → only → 都空 = 全支持。

    条目支持 fnmatch 通配符（* ? [seq]），对工作流名（不含 .json）大小写敏感匹配。
    静态声明（实例硬件能否承接）；动态 health（缺节点/缺模型）仅参考展示，不做门。
    拼错键 fail fast（extra="forbid"）。
    """

    model_config = ConfigDict(extra="forbid")
    exclude: list[str] = Field(default_factory=list)  # 排除（黑名单）：命中 = 该实例不支持
    only: list[str] = Field(default_factory=list)    # 只能（白名单）：非空时不命中 = 不支持


class ComfyUIInstanceConfig(BaseModel):
    """单个 ComfyUI 实例配置。"""

    name: str
    url: str
    password: str = ""
    workflow_rules: WorkflowRules = Field(default_factory=WorkflowRules)

    @field_validator("url")
    @classmethod
    def _normalize_url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v:
            raise ValueError("url 不能为空")
        return v


class RoutingWeights(BaseModel):
    """路由打分权重（P5.13）：score = pending × pending + running × running，越低越好。"""

    pending: float = 1.0
    running: float = 2.0


class RoutingConfig(BaseModel):
    """路由配置（P5.13）：仅供 describe 的 routing 块打分——实例选择由调用方完成
    （submit/upload 的 instance 必填，服务端不自动路由）。"""

    weights: RoutingWeights = Field(default_factory=RoutingWeights)


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 18800
    # MCP /mcp/ 的 Host/Origin 白名单（mcp 2.x DNS rebinding 防护，未配置=SDK 默认仅 localhost，
    # 非本机 Host 连 /mcp/ 返回 421）。支持 "host:*" 通配端口，如 "119.84.39.2:*"
    mcp_allowed_hosts: list[str] = []
    mcp_allowed_origins: list[str] = []


class ComfyUIConfig(BaseModel):
    """config.json 顶层结构。"""

    comfyui_instances: list[ComfyUIInstanceConfig]
    default_instance: str
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    command_token: str = ""
    query_token: str = ""
    workflows_dir: str = "workflows"
    output_dir: str = "output"
    log_dir: str = "log"
    # 清理机制（D14）
    output_retention_days: float = 7.0     # output/ 保留天数（≤0=不限）
    cleanup_interval_hours: float = 6.0    # 周期清理间隔（小时，≤0=仅启动跑一次）
    task_retention_hours: float = 24.0     # 终态任务保留时长（小时，≤0=不按时间裁剪）
    task_max_retained: int = 200           # 终态任务最大保留条数（≤0=不限；active 任务不受影响）


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowParam(BaseModel):
    """工作流输入/输出参数描述。

    kind: input | output
    param: 注入用的参数名（输入=INPUT_ 标题去掉前缀后的部分，或首个非连线输入键）
    default: 当前默认值（输入参数；输出为 None）
    """

    node_id: str
    class_type: str
    title: str
    kind: str
    param: Optional[str] = None
    default: Any = None

    def to_dict(self) -> dict:
        return self.model_dump()


class ExecuteResult(BaseModel):
    """同步执行工作流的返回。"""

    prompt_id: str
    instance: str
    outputs: list[str] = []          # 下载到本地 output/ 的文件路径（绝对路径）
    text_outputs: dict[str, str] = {}  # 标题 -> 文本内容
    progress_nodes: list[str] = []     # 执行过的节点 id（按序）
    elapsed: float = 0.0

    def to_dict(self) -> dict:
        return self.model_dump()
