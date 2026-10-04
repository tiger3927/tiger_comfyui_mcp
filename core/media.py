"""media：执行完成后从 history outputs 下载所有类型产物，落盘 output/。

不硬编码输出类型（images/videos/audio/... 全遍历，参考工程同款策略）。
本地文件名加 `{prefix}_{prompt8}_{序号}_` 前缀，防跨实例/跨任务同名覆盖。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

import aiohttp

from core.comfy_client import ComfyUIClient

logger = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+")


def safe_name(name: str) -> str:
    """去掉路径分隔与危险字符，保留中文。"""
    return _SAFE_NAME.sub("_", name).strip("_") or "file"


async def collect_outputs(
    session: aiohttp.ClientSession,
    client: ComfyUIClient,
    prompt_id: str,
    output_dir: Path,
    prefix: str,
    text_outputs: Optional[dict[str, str]] = None,
    history_retries: int = 6,
    retry_delay: float = 2.0,
) -> tuple[list[str], dict[str, str]]:
    """下载全部文件输出并（可选）保存文本输出。

    返回 (本地文件路径列表[绝对路径], 文本输出 {标题: 内容})。
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = safe_name(prefix)
    p8 = prompt_id[:8]

    local_paths: list[str] = []
    texts: dict[str, str] = dict(text_outputs or {})

    # 文本输出（WS 捕获的 OUTPUT_* 节点）
    for title, content in list(texts.items()):
        ext = "json" if title.endswith("_JSON") else "txt"
        target = output_dir / f"{prefix}_{p8}_{safe_name(title)}.{ext}"
        try:
            target.write_text(content, encoding="utf-8")
            local_paths.append(str(target.resolve()))
            logger.info("[media] 文本输出 %s -> %s", title, target.name)
        except OSError as e:
            logger.error("[media] 保存文本输出失败 %s: %s", title, e)

    history = await client.get_history(session, prompt_id,
                                       max_retries=history_retries,
                                       retry_delay=retry_delay)
    if not history:
        logger.error("[media] history 获取失败（%d 次重试后），仅返回已有文本输出", history_retries)
        return local_paths, texts

    history_data = history.get(prompt_id) or {}
    outputs = history_data.get("outputs") or {}
    if not outputs:
        logger.warning("[media] history 无 outputs 字段（任务可能无文件输出）")
        return local_paths, texts

    sid = 0
    for node_id, node_output in outputs.items():
        if not isinstance(node_output, dict):
            continue
        for output_type, items in node_output.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict) or "filename" not in item or "type" not in item:
                    continue
                filename = item["filename"]
                subfolder = item.get("subfolder", "")
                folder_type = item["type"]
                data = await client.get_file_content(session, filename, subfolder, folder_type)
                if not data:
                    logger.error("[media] 下载失败 node=%s type=%s file=%s",
                                 node_id, output_type, filename)
                    continue
                target = output_dir / f"{prefix}_{p8}_{sid:02d}_{safe_name(filename)}"
                target.write_bytes(data)
                local_paths.append(str(target.resolve()))
                sid += 1
                logger.info("[media] 下载 [%s] %s -> %s（%d bytes）",
                            output_type, filename, target.name, len(data))

    return local_paths, texts
