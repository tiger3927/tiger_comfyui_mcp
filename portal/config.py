"""门户配置：解析 config.json 的 "portal" 段 + credit_rules 初始种子。

门户包红线：只吃一个普通 dict（main.py 传入 config.json["portal"]），
不 import core/server、不依赖 ComfyUIConfig（见 Task-WWW.md §2.1）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_PORTAL = {
    "db_path": "data/portal.db",
    "rmb_per_credit": 0.01,
    "default_price": 1,
    "recharge_min": 10,
    "recharge_max": 5000,
    "recharge_auto_credit": True,
    "order_timeout_s": 1800,
    "sync_interval_s": 2,
    "max_active_per_user": 2,
    "jwt_ttl_hours": 24,
}


@dataclass
class PortalSettings:
    db_path: str = DEFAULT_PORTAL["db_path"]
    rmb_per_credit: float = DEFAULT_PORTAL["rmb_per_credit"]
    default_price: int = DEFAULT_PORTAL["default_price"]
    recharge_min: int = DEFAULT_PORTAL["recharge_min"]
    recharge_max: int = DEFAULT_PORTAL["recharge_max"]
    recharge_auto_credit: bool = DEFAULT_PORTAL["recharge_auto_credit"]
    order_timeout_s: int = DEFAULT_PORTAL["order_timeout_s"]
    sync_interval_s: int = DEFAULT_PORTAL["sync_interval_s"]
    max_active_per_user: int = DEFAULT_PORTAL["max_active_per_user"]
    jwt_ttl_hours: int = DEFAULT_PORTAL["jwt_ttl_hours"]
    # JWT 签名密钥：config.portal.jwt_secret 优先；缺省回落环境变量 PORTAL_JWT_SECRET；
    # 两者皆空则启动时拒绝（防误用默认密钥）。
    jwt_secret: str = ""
    public_base_url: str = ""          # 充值二维码 URL 前缀（复用 server.public_base_url 注入）

    @classmethod
    def from_dict(cls, raw: dict | None, *, public_base_url: str = "") -> "PortalSettings":
        raw = raw or {}
        kw = {k: raw[k] for k in DEFAULT_PORTAL if k in raw}
        secret = raw.get("jwt_secret") or os.environ.get("PORTAL_JWT_SECRET", "")
        return cls(jwt_secret=secret, public_base_url=public_base_url, **kw)

    @property
    def has_jwt_secret(self) -> bool:
        return bool(self.jwt_secret)


# ---- credit_rules 初始种子（§3.1 锚点；管理员可在后台改，即时生效）----
# 键与 §4 表列一一对应。fps=0 → 平台默认 24。price_per_mp：图片=每张每百万像素，
# 视频=每百万像素每帧（×秒×fps）。参数键名以工作流实际 INPUT_ 标题为准，未列的
# width/height 走 default_width/height 兜底。
@dataclass
class RuleSeed:
    pattern: str
    media: str
    price_per_mp: float = 0.0
    price_per_char: float = 0.0
    flat_price: int = 0
    fps: int = 0
    width_param: str | None = None
    height_param: str | None = None
    seconds_param: str | None = None
    char_param: str | None = None
    default_width: int | None = None
    default_height: int | None = None
    remark: str = ""


# 图片 1920×1080(2.0736MP)=300 分 → 144.676/MP；视频 720×1280(0.9216MP)@24fps 1s=3000 分
# → 135.626/MP·帧。
IMAGE_PPM = round(300 / (1920 * 1080 / 1e6), 4)       # 144.6762
VIDEO_PPM = round(3000 / (720 * 1280 / 1e6 * 24), 4)  # 135.6244

DEFAULT_RULES: list[RuleSeed] = [
    RuleSeed("hello", "flat", flat_price=0, remark="演示工作流，免费"),
    RuleSeed("qwen_image_21_t2i", "image", price_per_mp=IMAGE_PPM,
             width_param="width", height_param="height",
             default_width=1024, default_height=1024, remark="文生图，按输出分辨率"),
    RuleSeed("qwen_image_21_edit_10", "image", price_per_mp=IMAGE_PPM,
             default_width=1920, default_height=1080,
             remark="图编辑，输出跟参考图；无 W/H 参数→按 1080p 级=300 分（§13-5c）"),
    RuleSeed("video_minimax_h3_fasth3_f", "video", price_per_mp=VIDEO_PPM, fps=24,
             width_param="INPUT_WIDTH", height_param="INPUT_HEIGHT",
             seconds_param="INPUT_SECONDS_VALUE", remark="图生视频 I2V"),
    RuleSeed("video_minimax_h3_fasth3_fl", "video", price_per_mp=VIDEO_PPM, fps=24,
             width_param="INPUT_WIDTH", height_param="INPUT_HEIGHT",
             seconds_param="INPUT_SECONDS_VALUE", remark="图生视频（fl 变体）"),
    RuleSeed("video_minimax_h3_r2v", "video", price_per_mp=VIDEO_PPM, fps=24,
             width_param="INPUT_WIDTH", height_param="INPUT_HEIGHT",
             seconds_param="INPUT_SECONDS_VALUE", remark="参考图生视频"),
    RuleSeed("Infinitetalk_image_single", "video", price_per_mp=VIDEO_PPM, fps=24,
             remark="数字人口型，未列 W/H→默认 720×1280"),
    RuleSeed("vibevoice_tts_clone", "audio", price_per_char=100.0, char_param="text",
             remark="TTS：积分/100 字（price_per_char=100 → 1 分/字，§13-5b 待定占位）"),
    RuleSeed("qwen3_tts_clone", "audio", price_per_char=100.0, char_param="text",
             remark="TTS 占位价，待核"),
    RuleSeed("qwen3_tts_design", "audio", price_per_char=100.0, char_param="text",
             remark="TTS 占位价，待核"),
]
