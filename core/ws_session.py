"""WS 会话：一次执行新建一条 WebSocket，监听至任务终结。

借鉴参考工程（只读）的消息路由逻辑，并补强：
- 每次执行新建连接，不做常驻重连状态机（一期）
- 心跳保活（aiohttp heartbeat）
- 总超时保护，避免死等
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

import aiohttp

from core.comfy_client import ComfyUIClient

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, str, str, Optional[str]], Awaitable[None]]
# 签名：async def on_progress(node_id, status, prompt_id, error=None)


@dataclass
class WsExecutionResult:
    success: bool = False
    prompt_id: str = ""
    error: Optional[str] = None
    interrupted: bool = False
    disconnected: bool = False
    started: bool = False      # 收到本 prompt 首个节点级 executing 事件（真正开跑）
    timed_out: bool = False    # 命中总超时
    progress_nodes: list[str] = field(default_factory=list)
    text_outputs: dict[str, str] = field(default_factory=dict)  # OUTPUT_* 标题 -> 文本


def _is_output_node(workflow: dict, node_id: str) -> Optional[str]:
    """若该节点 _meta.title 以 OUTPUT_ 开头，返回 title。"""
    node = workflow.get(node_id)
    if not isinstance(node, dict):
        return None
    title = (node.get("_meta") or {}).get("title", "")
    return title if isinstance(title, str) and title.startswith("OUTPUT_") else None


async def execute_prompt(
    session: aiohttp.ClientSession,
    client: ComfyUIClient,
    submit: Callable[[], Awaitable[Optional[dict]]],
    workflow: dict[str, Any],
    on_progress: Optional[ProgressCallback] = None,
    total_timeout: float = 3600.0,
    task_client_id: Optional[str] = None,
) -> WsExecutionResult:
    """连接 WS -> 提交任务 -> 监听至终结，返回执行结果。

    submit: 无参 async 工厂，调用即提交（POST /prompt），返回 {prompt_id,...}。
    先连 WS 再提交，避免错过第一个 executing 消息。
    task_client_id：每任务独立的 ?clientId=（与 submit 内 queue_prompt 的
    client_id 一致），避免同实例并发任务互顶 WS slot 导致事件丢失。
    """
    result = WsExecutionResult()
    ws_headers = {
        "Origin": client.base_url,
        "Cookie": client.cookie_str or "",
    }
    if not client.cookie_str:
        ws_headers.pop("Cookie")

    try:
        async with session.ws_connect(client.ws_url_for(task_client_id),
                                      headers=ws_headers, heartbeat=30.0) as ws:
            logger.debug("[%s] WS 已连接（client_id=%s）",
                         client.instance.name, task_client_id or client.client_id)

            resp = await submit()
            if not resp or "prompt_id" not in resp:
                result.error = "任务提交失败（/prompt 无 prompt_id）"
                return result
            prompt_id = resp["prompt_id"]
            result.prompt_id = prompt_id
            logger.info("[%s] 已提交 prompt_id=%s", client.instance.name, prompt_id)
            if on_progress:
                await _safe_progress(on_progress, None, "started", prompt_id)

            deadline = asyncio.get_event_loop().time() + total_timeout
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    result.timed_out = True
                    result.error = f"执行超时（>{total_timeout:.0f}s，含排队等待）"
                    logger.error("[%s] prompt %s 超时", client.instance.name, prompt_id)
                    break
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=remaining)
                except (asyncio.TimeoutError, TimeoutError):
                    result.timed_out = True
                    result.error = f"执行超时（>{total_timeout:.0f}s，含排队等待）"
                    break

                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        message = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue
                    mtype = message.get("type")
                    data = message.get("data") or {}

                    if mtype == "status":
                        continue
                    elif mtype == "executing":
                        if data.get("prompt_id") != prompt_id:
                            continue
                        node = data.get("node")
                        if node is None:
                            logger.info("[%s] prompt %s 执行完成", client.instance.name, prompt_id)
                            result.success = True
                            if on_progress:
                                await _safe_progress(on_progress, None, "completed", prompt_id)
                            break
                        if not result.started:
                            result.started = True
                        if node not in result.progress_nodes:
                            result.progress_nodes.append(node)
                        if on_progress:
                            await _safe_progress(on_progress, str(node), "executing", prompt_id)
                    elif mtype == "execution_start":
                        # newgoai 等实例的执行事件词汇（无节点级 executing）：
                        # execution_start/executed/execution_success 代替
                        if data.get("prompt_id") != prompt_id:
                            continue
                        result.started = True
                    elif mtype == "executed":
                        node_id = data.get("node")
                        if not node_id or data.get("prompt_id", None) not in (None, prompt_id):
                            continue
                        # 逐节点 completed 即节点级进度信号（标准 ComfyUI 也有该事件）
                        if not result.started:
                            result.started = True
                        if node_id not in result.progress_nodes:
                            result.progress_nodes.append(node_id)
                        if on_progress:
                            await _safe_progress(on_progress, str(node_id),
                                                 "executing", prompt_id)
                        title = _is_output_node(workflow, node_id)
                        if title:
                            output = data.get("output") or {}
                            text_items = output.get("text")
                            if isinstance(text_items, list) and text_items:
                                result.text_outputs[title] = str(text_items[0])
                                logger.info("[%s] 捕获文本 %s: %s",
                                            client.instance.name, title,
                                            str(text_items[0])[:120])
                    elif mtype == "execution_error":
                        if data.get("prompt_id") != prompt_id:
                            continue
                        result.error = (f"节点 {data.get('node_id')}（{data.get('node_type')}）"
                                        f"错误：{data.get('exception_message')}")
                        logger.error("[%s] 执行错误：%s", client.instance.name, result.error)
                        if on_progress:
                            await _safe_progress(on_progress, data.get("node_id"),
                                                 "error", prompt_id, result.error)
                        break
                    elif mtype == "execution_interrupted":
                        if data.get("prompt_id") != prompt_id:
                            continue
                        result.interrupted = True
                        logger.warning("[%s] prompt %s 被中断", client.instance.name, prompt_id)
                        if on_progress:
                            await _safe_progress(on_progress, None, "interrupted", prompt_id)
                        break

                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING,
                                  aiohttp.WSMsgType.ERROR):
                    result.disconnected = True
                    logger.error("[%s] WS 断开（prompt %s 未见终态，/history 兜底）",
                                 client.instance.name, prompt_id)
                    recovered, fallback_err = await _wait_history_terminal(
                        session, client, prompt_id, deadline)
                    if recovered:
                        result.success = True
                        if on_progress:
                            await _safe_progress(on_progress, None, "completed", prompt_id)
                    else:
                        result.error = result.error or fallback_err
                    break
    except aiohttp.WSServerHandshakeError as e:
        result.error = f"WS 握手失败：{e}"
        logger.error("[%s] %s", client.instance.name, result.error)
    except Exception as e:
        result.error = f"WS 执行异常：{e}"
        logger.exception("[%s] WS 执行异常", client.instance.name)
    return result


async def _wait_history_terminal(session: aiohttp.ClientSession, client: ComfyUIClient,
                                 prompt_id: str, deadline: float
                                 ) -> tuple[bool, Optional[str]]:
    """WS 异常断开后，每 15s 轮询 GET /history/{prompt_id} 至 deadline，
    确认远端任务是否实际到达终态（加固 c：远端可能已跑完，直接 FAILED 会丢产物）。

    返回 (远端完成, 兜底错误文案)：
    - 完成 → (True, None)，调用方照常收集产物；
    - 远端明确执行错误 → (False, 错误文案)；
    - deadline 到仍未知 → (False, "连接断开，远端状态未知…")。
    """
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            return False, ("连接断开，远端状态未知"
                           "（远端任务可能仍在执行，产物无法取回）")
        try:
            data = await client.get_history(session, prompt_id,
                                            max_retries=2, retry_delay=1.0)
        except Exception as e:
            logger.debug("[%s] /history 兜底探测异常：%s", client.instance.name, e)
            data = None
        entry = (data or {}).get(prompt_id) or {}
        status = entry.get("status") or {}
        if status.get("completed"):
            logger.warning("[%s] WS 断开但远端任务已完成（/history 兜底恢复）prompt=%s",
                           client.instance.name, prompt_id)
            return True, None
        if status.get("status_str") == "error":
            return False, "远端执行出错（WS 断开后 /history 兜底发现）"
        await asyncio.sleep(min(15.0, max(remaining, 0.0)))


async def _safe_progress(cb: ProgressCallback, node_id, status: str,
                         prompt_id: str, error: Optional[str] = None) -> None:
    """进度回调吞异常，绝不影响主执行流。"""
    try:
        await cb(node_id, status, prompt_id, error)
    except Exception:
        logger.exception("进度回调异常（已忽略）")
