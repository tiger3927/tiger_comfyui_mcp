# video_minimax_h3_fasth3_l
## 分类
- 图生视频（MiniMax H3 快速版，仅尾帧，音画同出）
## 介绍
- MiniMax H3 系列快速图生视频：给一张尾帧图 + 提示词，生成从合理前序状态起、逐步收敛到尾帧的视频，同时产出声音（音画同出，人物说话/环境声一体产出，无需另配 TTS）
- fasth3 = 8 步蒸馏快速版（8step v2 pruned int8 convrot），速度快
- 无法带入克隆参考音

## 参数
- INPUT_PROMPT_TEXT   必填，提示词（Text Multiline 节点，默认"人物说"好想出去玩""）
- INPUT_IMAGE_LAST_FILE   必填，尾帧图文件名（先经 REST 上传再注入：`comfyui_request_upload_ticket` 取票据 → curl 直传）
- INPUT_WIDTH_VALUE / INPUT_HEIGHT_VALUE  选填，输出宽高（默认 720×1280 竖版，nearest-exact 居中裁切，32 整除）
- INPUT_SECONDS_VALUE   必填，视频时长秒数（默认 5，**最长 20s**）
- INPUT_SEED   选填，随机种子（easy seed，默认 42）

## 提示词规范（必须遵守）
- **必须按 tiger_comfyui_director 技能的 minimax-h3-prompt-writing 子技能编写**（本工作流为 L2VA 模式：推断开场，结尾收敛到尾帧）
- 结构：尾帧对齐行 `How the reference pictures align with the target video — <Picture 1> (from [Shot N]) aligns with the S.SS-second mark of the target video.`（N=实际最后一镜序号，S.SS=时长两位小数）+ 空行 + 三核心字段
- 三核心字段：`integrated_multimodal_description` + `overall_soundscape` + `non_diegetic_music`（同 f 版）
- L2VA 要点：`<Picture 1>` 是尾帧，属于最后一个 `[Shot N]`（不天然属于 Shot 1）；正文不复述静态图，而是推断合理的前序状态，描述人物/物体/镜头/构图逐步逼近尾帧的收敛路径；**倾向单镜头**，末尾必须落入尾帧确立的最终姿态/构图/光线
- 正文用英文；对白/歌词/画面文字保留原语言；时长 4–15s 与描述匹配
- 模板：`references/minimax-h3-prompt-writing/references/base-en.txt` 之 L2VA / Case 4

## 预计时间
- 约 50s（5s 视频，与 f 版同一 8 步蒸馏管线，单任务执行同量级）；耗时随时长线性增长，20s 视频预计 ~3 分钟量级

## 输出文件的前缀
- minimax-h3-fasth3（远端 SaveVideo filename_prefix）
- 本地归档：`{实例名}_video_minimax_h3_fasth3_l_{prompt8}_{idx}_minimax-h3-fasth3_0000N.mp4`
## 输出文件
- 一个 mp4 视频（**带声音**，24fps，音画同出）

## 所需节点（class_type，缺则执行报 Unknown node type）
- `SaveVideo`、`LoadImage`、`ImpactInt`、`ImageResizeKJv2`、`easy seed`、`VAELoader`、`VAEDecodeAudio`、`VAEDecode`、`KSamplerSelect`、`BasicScheduler`、`SamplerCustomAdvanced`、`BasicGuider`、`UNETLoader`、`CLIPLoader`、`RandomNoise`、`CreateVideo`、`MiniMaxH3ImageToVideo`、`ComfyMathExpression`、`PrimitiveFloat`、`BlockSparseAttention`、`ModelAttentionBackend`、`MiniMaxH3SigmaShift`、`Text Multiline`
