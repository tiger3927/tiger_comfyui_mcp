# video_minimax_h3_fasth3_fl
## 分类
- 图生视频（MiniMax H3 快速版，首尾帧，音画同出）
## 介绍
- MiniMax H3 系列快速图生视频：给首帧图 + 尾帧图 + 提示词，生成从首帧连续演变到尾帧的视频，同时产出声音（音画同出，人物说话/环境声一体产出，无需另配 TTS）
- fasth3 = 8 步蒸馏快速版（8step v2 pruned int8 convrot），速度快
- 无法带入克隆参考音

## 参数
- INPUT_PROMPT_TEXT   提示词（Text Multiline 节点，默认"人物说"好想出去玩""）
- INPUT_IMAGE_1_FILE   首帧图文件名（uploads）
- INPUT_IMAGE_2_FILE   尾帧图文件名（uploads）
- INPUT_WIDTH_VALUE / INPUT_HEIGHT_VALUE  输出宽高（默认 720×1280 竖版，nearest-exact 居中裁切，32 整除）
- INPUT_SECONDS_VALUE   视频时长秒数（默认 5，**最长 20s**）
- INPUT_SEED   随机种子（easy seed，默认 42）

## 提示词规范（必须遵守）
- **必须按 tiger_comfyui_director 技能的 minimax-h3-prompt-writing 子技能编写**（本工作流为 FL2VA 模式：描述首帧到尾帧之间的连续路径）
- 结构：首尾帧对齐行 `How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video.`（S.SS=时长，两位小数）+ 空行 + 三核心字段
- 三核心字段：`integrated_multimodal_description` + `overall_soundscape` + `non_diegetic_music`（同 f 版）
- FL2VA 要点：正文不复述两张静态图，写两帧之间的运动路径（主体位移/姿态变化/构图演变/光线过渡）；**倾向单镜头**，尾帧必须在最后一个 `[Shot N]` 收尾到达
- 正文用英文；对白/歌词/画面文字保留原语言；时长 4–15s 与描述匹配
- 模板：`references/minimax-h3-prompt-writing/references/base-en.txt` 之 FL2VA / Case 3

## 预计时间
- 约 50s（5s 视频，实测任务 102s 含 ~50s 排队，单任务执行与 f 版同量级——同一 8 步蒸馏管线）；耗时随时长线性增长，20s 视频预计 ~3 分钟量级

## 输出文件的前缀
- minimax-h3-fasth3（远端 SaveVideo filename_prefix）
- 本地归档：`{实例名}_video_minimax_h3_fasth3_fl_{prompt8}_{idx}_minimax-h3-fasth3_0000N.mp4`
## 输出文件
- 一个 mp4 视频（**带声音**，24fps，音画同出）

## 所需节点（class_type，缺则执行报 Unknown node type）
- `SaveVideo`、`LoadImage`、`ImpactInt`、`ImageResizeKJv2`、`easy seed`、`VAELoader`、`VAEDecodeAudio`、`VAEDecode`、`KSamplerSelect`、`BasicScheduler`、`SamplerCustomAdvanced`、`BasicGuider`、`UNETLoader`、`CLIPLoader`、`RandomNoise`、`CreateVideo`、`MiniMaxH3ImageToVideo`、`ComfyMathExpression`、`PrimitiveFloat`、`BlockSparseAttention`、`ModelAttentionBackend`、`MiniMaxH3SigmaShift`、`Text Multiline`
