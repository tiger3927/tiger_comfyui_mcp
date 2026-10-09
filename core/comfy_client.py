"""ComfyUIClient：单实例 HTTP 通信（登录 + REST）。

设计沿用参考工程 tools/comfyui_cli.py（只读借鉴）并做以下调整：
- url 支持完整 URL（http:// / https://），ws_url 自动推导
- 所有方法接收外部 session（由调用方管理生命周期，一次执行一个 session）
- 不硬编码输出类型（media.py 负责遍历 outputs 所有 key）
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Optional

import aiohttp

from schemas.models import ComfyUIInstanceConfig

logger = logging.getLogger(__name__)


def _derive_ws_url(base_url: str, client_id: str) -> str:
    """https://host[:port] -> wss://host[:port]/ws?clientId=..."""
    ws_base = base_url
    if ws_base.startswith("https://"):
        ws_base = "wss://" + ws_base[len("https://"):]
    elif ws_base.startswith("http://"):
        ws_base = "ws://" + ws_base[len("http://"):]
    return f"{ws_base}/ws?clientId={client_id}"


def extract_ckpt_names(object_info: Optional[dict]) -> list[str]:
    """从 /object_info 提取 CheckpointLoaderSimple 可用模型列表。

    结构：{ClassName: {input: {required/optional: {ckpt_name: [列表, "COMBO"]}}}}
    """
    if not object_info:
        return []
    input_schema = (object_info.get("CheckpointLoaderSimple") or {}).get("input") or {}
    for section in ("required", "optional"):
        s = input_schema.get(section)
        if isinstance(s, dict) and "ckpt_name" in s:
            raw = s["ckpt_name"]
            if isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], list):
                raw = raw[0]  # [列表, "COMBO"] 形式
            return raw if isinstance(raw, list) else []
    raw = input_schema.get("ckpt_name")  # 扁平结构兜底
    if isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], list):
        raw = raw[0]
    return raw if isinstance(raw, list) else []


def _combo_values(schema_value: Any) -> Optional[list[str]]:
    """从 object_info 参数 schema 提取 COMBO 值列表；非 COMBO 参数返回 None。

    双形态兼容：
    - `[值列表, "COMBO"]`（newgoai 2026-10-03 实测）：首元素是 list → 解包
    - 纯字符串列表（标准 ComfyUI）
    typed 参数形如 `["INT", {...}]` / `["MODEL", {...}]`（[类型名, dict]）→ 非 COMBO。
    """
    if not isinstance(schema_value, (list, tuple)) or not schema_value:
        return None
    first = schema_value[0]
    if isinstance(first, (list, tuple)):
        return [str(x) for x in first]
    if len(schema_value) == 2 and isinstance(schema_value[1], dict):
        return None  # ["INT", {...}] typed 参数
    if all(isinstance(x, str) for x in schema_value):
        return list(schema_value)
    return None


def check_workflow(object_info: Optional[dict], prompt: dict) -> dict:
    """通用预检（P5.8）：节点存在性 + COMBO 参数值存在性（模型文件等）。

    返回：
    - nodes_missing:  [{node_id, class_type}] —— class_type 不在 object_info（自定义节点未安装，必挂）
    - models_missing: [{node_id, class_type, param, value, available_count, available_sample}]
                      —— 工作流实际提供的字面量不在 COMBO 值列表内
    - executable:     两列表皆空（必要非充分——不覆盖 OOM/文件损坏/动态路径加载）

    规则：只检查 inputs 实际提供的参数（未提供=用默认值，不计缺失）；
    连线值（list/tuple，如 [node_id, idx]）与空串跳过；object_info 拿不到时不阻断（两列表空）。
    """
    nodes_missing: list[dict] = []
    models_missing: list[dict] = []
    if not object_info or not isinstance(prompt, dict):
        return {"nodes_missing": nodes_missing, "models_missing": models_missing,
                "executable": True}
    for nid, node in prompt.items():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type")
        schema = object_info.get(ct)
        if not isinstance(schema, dict):
            nodes_missing.append({"node_id": str(nid), "class_type": str(ct)})
            continue
        input_schema = schema.get("input") or {}
        provided = node.get("inputs") or {}
        for section in ("required", "optional"):
            for param, spec in (input_schema.get(section) or {}).items():
                if param not in provided:
                    continue
                values = _combo_values(spec)
                if values is None:
                    continue
                value = provided[param]
                if isinstance(value, (list, tuple)) or not isinstance(value, str) \
                        or not value:
                    continue
                if value not in values:
                    models_missing.append({
                        "node_id": str(nid), "class_type": str(ct), "param": param,
                        "value": value, "available_count": len(values),
                        "available_sample": values[:5],
                    })
    return {"nodes_missing": nodes_missing, "models_missing": models_missing,
            "executable": not nodes_missing and not models_missing}


class ComfyUIClient:
    """绑定单个 ComfyUI 实例的客户端。线程内单例复用，不持有长生命周期 session。"""

    def __init__(self, instance: ComfyUIInstanceConfig):
        self.instance = instance
        self.client_id = str(uuid.uuid4())
        self.password = instance.password
        url = instance.url
        if url.startswith(("http://", "https://")):
            self.base_url = url
        else:
            self.base_url = f"http://{url}"
        self.ws_url = _derive_ws_url(self.base_url, self.client_id)
        self.cookie_str: Optional[str] = None
        self._object_info: Optional[dict] = None
        self._object_info_ts: float = 0.0

    # ------------------------------------------------------------------
    # session
    # ------------------------------------------------------------------
    @staticmethod
    def make_session(timeout_total: int = 300) -> aiohttp.ClientSession:
        """新建 HTTP session（默认 5 分钟总超时；WS 长连接另计）。"""
        return aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout_total, sock_read=300)
        )

    # ------------------------------------------------------------------
    # 登录
    # ------------------------------------------------------------------
    async def login(self, session: aiohttp.ClientSession) -> bool:
        """探测是否需要登录；需要则 POST /login 抓 Set-Cookie 注入 session headers。

        成功=True。已登录过的 cookie 保持复用（每次新 session 需重新登录——
        一期按"每次执行新建 session 并登录"处理，简单可靠）。
        """
        queue_url = f"{self.base_url}/queue"
        try:
            # sock_connect 限定 TCP 建连时长：不可达实例快速失败（默认建连超时可达 213s）
            async with session.get(
                queue_url,
                timeout=aiohttp.ClientTimeout(total=10, sock_connect=2)
            ) as resp:
                if resp.status == 200:
                    ct = resp.headers.get("Content-Type", "")
                    if "application/json" in ct:
                        logger.info("[%s] 无需登录", self.instance.name)
                        return True
                    # HTML（登录页跳转）或 json 解码失败都视为需要登录
                    logger.info("[%s] 需要登录（/queue 返回 %s %s）",
                                self.instance.name, resp.status, ct)
        except Exception as e:
            logger.debug("[%s] /queue 探测失败：%s，尝试登录", self.instance.name, e)

        login_url = f"{self.base_url}/login"
        try:
            async with session.post(
                login_url, data={"password": self.password}, allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=15, sock_connect=5),
            ) as resp:
                if resp.status == 302:
                    raw_cookie = resp.headers.get("Set-Cookie")
                    if raw_cookie:
                        self.cookie_str = raw_cookie.split(";")[0]
                        session.headers.update({"Cookie": self.cookie_str})
                        logger.info("[%s] 登录成功，cookie 已注入", self.instance.name)
                        return True
                    logger.error("[%s] 登录 302 但无 Set-Cookie", self.instance.name)
                    return False
                logger.error("[%s] 登录失败：status=%s（200=密码错误/无登录插件）",
                             self.instance.name, resp.status)
                return False
        except Exception as e:
            logger.error("[%s] 登录异常：%s", self.instance.name, e)
            return False

    # ------------------------------------------------------------------
    # 队列 / 任务
    # ------------------------------------------------------------------
    def ws_url_for(self, client_id: Optional[str] = None) -> str:
        """WS 连接 URL。

        传独立 client_id（每任务一个 uuid）可避免同实例多任务共用一个
        ?clientId= slot：服务端按 clientId 注册 WS 会话，同 clientId 的新连接
        会顶掉旧连接，事件也只路由到该 slot（newgoai 实测：共享 client_id
        时并发任务 N-1 个收不到终态事件）。
        """
        return _derive_ws_url(self.base_url, client_id or self.client_id)

    async def queue_prompt(self, session: aiohttp.ClientSession,
                           prompt: dict[str, Any],
                           client_id: Optional[str] = None) -> Optional[dict]:
        """POST /prompt 提交 API 格式工作流。返回 {prompt_id, number} 或 None。

        client_id：与 ws_url_for() 配对的每任务标识（服务端据此定向路由
        该 prompt 的执行事件到对应 WS 会话）。
        """
        url = f"{self.base_url}/prompt"
        payload = {"prompt": prompt, "client_id": client_id or self.client_id}
        try:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    return await resp.json()
                text = await resp.text()
                logger.error("[%s] /prompt 失败 %s: %s", self.instance.name, resp.status, text[:500])
                return None
        except Exception as e:
            logger.error("[%s] /prompt 异常：%s", self.instance.name, e)
            return None

    async def get_history(self, session: aiohttp.ClientSession, prompt_id: str,
                          max_retries: int = 5, retry_delay: float = 2.0) -> Optional[dict]:
        """GET /history/{id}，404 重试（任务刚完成时 history 可能未写盘）。"""
        url = f"{self.base_url}/history/{prompt_id}"
        for attempt in range(max_retries):
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if prompt_id in data:
                            return data
                        logger.warning("[%s] history 200 但无 %s（attempt %d）",
                                       self.instance.name, prompt_id, attempt + 1)
                    elif resp.status == 404:
                        logger.debug("[%s] history 404（attempt %d/%d）",
                                     self.instance.name, attempt + 1, max_retries)
                    else:
                        logger.error("[%s] history %s（attempt %d）",
                                     self.instance.name, resp.status, attempt + 1)
            except Exception as e:
                logger.debug("[%s] history 异常（attempt %d）：%s",
                             self.instance.name, attempt + 1, e)
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
        return None

    async def get_queue(self, session: aiohttp.ClientSession) -> Optional[dict]:
        """GET /queue -> {queue_running: [...], queue_pending: [...]}"""
        url = f"{self.base_url}/queue"
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    try:
                        return await resp.json(content_type=None)
                    except Exception:
                        logger.warning("[%s] /queue 返回非 JSON（可能未登录）", self.instance.name)
                        return None
                logger.error("[%s] /queue 失败 %s", self.instance.name, resp.status)
                return None
        except Exception as e:
            logger.error("[%s] /queue 异常：%s", self.instance.name, e)
            return None

    async def object_info(self, session: aiohttp.ClientSession,
                          refresh: bool = False) -> Optional[dict]:
        """GET /object_info：节点 schema 及当前模型列表等（5 分钟缓存）。"""
        import time
        if not refresh and self._object_info and time.time() - self._object_info_ts < 300:
            return self._object_info
        url = f"{self.base_url}/object_info"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    self._object_info = data
                    self._object_info_ts = time.time()
                    return data
                logger.error("[%s] /object_info 失败 %s", self.instance.name, resp.status)
                return None
        except Exception as e:
            logger.error("[%s] /object_info 异常：%s", self.instance.name, e)
            return None

    async def delete_from_queue(self, session: aiohttp.ClientSession, prompt_id: str) -> bool:
        """POST /queue {delete:[id]} 删除 pending 任务。"""
        url = f"{self.base_url}/queue"
        try:
            async with session.post(url, json={"delete": [prompt_id]}) as resp:
                if resp.status == 200:
                    logger.info("[%s] 已从队列删除 %s", self.instance.name, prompt_id)
                    return True
                logger.error("[%s] 删队列失败 %s", self.instance.name, resp.status)
                return False
        except Exception as e:
            logger.error("[%s] 删队列异常：%s", self.instance.name, e)
            return False

    async def interrupt(self, session: aiohttp.ClientSession,
                        prompt_id: Optional[str] = None) -> bool:
        """POST /interrupt 中断执行中的任务。

        prompt_id 非空时带 JSON body {"prompt_id": ...}：改动版 ComfyUI
        （newgoai 服务端）仅当该 prompt 正在执行才精准中断，否则跳过
        （多实例/共享实例并发安全）；vanilla ComfyUI 忽略请求体 → 仍全局
        中断，行为不变（向后兼容，无需探测实例类型）。
        """
        url = f"{self.base_url}/interrupt"
        try:
            payload = {"prompt_id": prompt_id} if prompt_id else None
            async with session.post(url, json=payload) as resp:
                ok = resp.status == 200
                logger.info("[%s] /interrupt -> %s", self.instance.name, resp.status)
                return ok
        except Exception as e:
            logger.error("[%s] /interrupt 异常：%s", self.instance.name, e)
            return False

    # ------------------------------------------------------------------
    # 文件
    # ------------------------------------------------------------------
    async def upload_image(self, session: aiohttp.ClientSession, file_path: str,
                           image_type: str = "input", overwrite: bool = True) -> Optional[dict]:
        """POST /upload/image（multipart）。返回 {name, subfolder, type}。"""
        url = f"{self.base_url}/upload/image"
        p = Path(file_path)
        if not p.is_file():
            logger.error("上传失败：文件不存在 %s", file_path)
            return None
        data = aiohttp.FormData()
        data.add_field("image", p.open("rb"), filename=p.name,
                       content_type="application/octet-stream")
        data.add_field("type", image_type)
        data.add_field("overwrite", "true" if overwrite else "false")
        try:
            async with session.post(url, data=data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    # 写操作使缓存失效：新上传媒体改变该实例 LoadImage COMBO 列表，
                    # 否则"上传→立即执行"的预检会用旧列表误报缺模型（5 分钟窗口内）
                    self._object_info = None
                    self._object_info_ts = 0.0
                    logger.info("[%s] 上传成功：%s（object_info 缓存已失效）",
                                self.instance.name, result.get("name"))
                    return result
                logger.error("[%s] 上传失败 %s", self.instance.name, resp.status)
                return None
        except Exception as e:
            logger.error("[%s] 上传异常：%s", self.instance.name, e)
            return None

    async def get_file_content(self, session: aiohttp.ClientSession, filename: str,
                               subfolder: str = "", folder_type: str = "output") -> Optional[bytes]:
        """GET /view?filename=&subfolder=&type= 下载文件字节。"""
        query = urllib.parse.urlencode(
            {"filename": filename, "subfolder": subfolder, "type": folder_type}
        )
        url = f"{self.base_url}/view?{query}"
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.read()
                logger.error("[%s] /view 下载 %s 失败 %s",
                             self.instance.name, filename, resp.status)
                return None
        except Exception as e:
            logger.error("[%s] /view 下载 %s 异常：%s", self.instance.name, filename, e)
            return None

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    async def get_status(self, session: aiohttp.ClientSession,
                         auto_login: bool = True) -> dict:
        """健康/负载摘要：connected、队列长度、system_stats（可选）。

        auto_login=True：/queue 非 JSON（需登录）时自动 POST /login 再探测。
        """
        out: dict[str, Any] = {"name": self.instance.name, "url": self.base_url}
        queue = await self.get_queue(session)
        if queue is None and auto_login and self.password:
            if await self.login(session):
                queue = await self.get_queue(session)
        if queue is None:
            out.update(connected=False)
            return out
        out.update(
            connected=True,
            queue_running=len(queue.get("queue_running", [])),
            queue_pending=len(queue.get("queue_pending", [])),
        )
        try:
            async with session.get(f"{self.base_url}/system_stats",
                                   timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    stats = await resp.json()
                    out["devices"] = [
                        {"name": d.get("name"), "vram_free": d.get("vram_free"),
                         "vram_total": d.get("vram_total")}
                        for d in stats.get("devices", [])
                    ]
        except Exception:
            pass
        return out
