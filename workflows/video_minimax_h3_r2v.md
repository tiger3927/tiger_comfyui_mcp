# video_minimax_h3_r2v

## 分类
- 参考转视频（MiniMax H3 r2v，混合多参考：图片 + 视频 + 音频，每类 0–N 可变数量，音画同出）

## 介绍
- 采用 MiniMax H3 ref2va 模型（int8 UNet + Qwen3-VL 32B nvfp4 CLIP + 视频/音频双 VAE，res_multistep/simple 采样）
- 混合多参考：0–9 张参考图 + 0–3 段参考视频 + 0–3 段独立参考音频，按提示词把参考内容组合/替换进目标视频；音画同出
- 参考视频的自带音频可同时处理`，无需单独抽离视频的音频作为参数
- Turbo 开关默认开（4 步 turbo LoRA）；关则走 20 步全质量
- 输出宽高由 INPUT_WIDTH/HEIGHT 决定（32 取整），**不跟参考图宽高比**；时长由 INPUT_SECONDS 决定（最少 5s，最长20s）


## 参数
- INPUT_PROMPT_TEXT   必填，提示词（描述参考图/视频/音频如何组合进目标视频，如"在 Video 1 中，用 Image 1 中的人物替换原视频里的表演者…"）
- INPUT_TURBO_BOOL   选填，Turbo 开关（默认 true=4 步快出；false=20 步全质量）
- INPUT_SECONDS_VALUE   选填，视频时长秒数（默认 5）
- INPUT_WIDTH_VALUE   选填，输出宽度（默认 720，32 取整）
- INPUT_HEIGHT_VALUE   选填，输出高度（默认 1280，32 取整）
- INPUT_IMAGE_1_FILE   选填：参考图1文件名（先经 REST 上传再注入：`comfyui_request_upload_ticket` 取票据 → curl 直传；JSON 里的默认图名仅占位）
- INPUT_IMAGE_2_FILE   选填：参考图2文件名（同上）
- INPUT_IMAGE_3_FILE   选填：参考图3文件名（同上）
- INPUT_IMAGE_4_FILE   选填：参考图4文件名（同上）
- INPUT_IMAGE_5_FILE   选填：参考图5文件名（同上）
- INPUT_IMAGE_6_FILE   选填：参考图6文件名（同上）
- INPUT_IMAGE_7_FILE   选填：参考图7文件名（同上）
- INPUT_IMAGE_8_FILE   选填：参考图8文件名（同上）
- INPUT_IMAGE_9_FILE   选填：参考图9文件名（同上）
- INPUT_VIDEO_1_FILE   选填：参考视频1文件名（同上；其自带音频自动抽取为参考音频）
- INPUT_VIDEO_2_FILE   选填：参考视频2文件名（同上）
- INPUT_VIDEO_3_FILE   选填：参考视频3文件名（同上）
- INPUT_AUDIO_1_FILE   选填：独立参考音频1文件名（同上；不随参考视频走，单独作参考音色/声音素材）
- INPUT_AUDIO_2_FILE   选填：独立参考音频2文件名（同上）
- INPUT_AUDIO_3_FILE   选填：独立参考音频3文件名（同上）

说明：
- 图/视频/音频三类**各自独立可变**：每类 0 个合法（全 0 = 纯文生视频）；某类 ≥1 时必须**从 1 号起连续提供**（如 2 段视频 = 1/2，缺号或缺 1 号报明确错误）
- 参考视频数量决定 `ref_video_audios` 数量（每段视频的音频自动进参考），与独立参考音频 `ref_audios` 互不占用编号

## 预计时间
- turbo加速情况下，5秒视频耗时1m
- 实测明细（mifengzhaopu，2026-10-10）：5s / 720×1280 / Turbo 4 步 / 全 0 参考纯文生视频，任务执行段 ≈57s；耗时随时长线性增长，20 步全质量（INPUT_TURBO_BOOL=false）约为其 4–5 倍

## 输出文件的前缀
- {实例名}_video_minimax_h3_r2v（comfyui执行远端保存前缀 MiniMax_H3_r2v）

## 所需节点（class_type，缺则执行报 Unknown node type）
- `LoadImage`、`LoadVideo`、`GetVideoComponents`、`LoadAudio`、`UNETLoader`、`CLIPLoader`、`VAELoader`、`KSamplerSelect`、`BasicScheduler`、`BasicGuider`、`SamplerCustomAdvanced`、`RandomNoise`、`ComfySwitchNode`、`LoraLoaderModelOnly`、`PrimitiveInt`、`PrimitiveFloat`、`PrimitiveBoolean`、`PrimitiveStringMultiline`、`ImpactInt`、`ComfyMathExpression`、`MiniMaxH3ReferenceToVideo`、`VAEDecode`、`VAEDecodeAudio`、`CreateVideo`、`SaveVideo`
