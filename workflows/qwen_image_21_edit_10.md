# qwen_image_21_edit_10

## 分类
- 图像编辑（Qwen-Image 2.1，1–10 张参考图，可变数量）
## 介绍
- 采用 Qwen-Image 2.1 模型（int8 量化 UNet + Qwen3-VL 8B 文本编码 + 2.1 VAE，euler/simple 25 步）
- i2i 编辑模式：1–10 张参考图 + 编辑提示词；PE（MTP）增强器（i2i preset、思考恒开）结合参考图生成正面/负面提示与图像条件 latent
- 输出分辨率由编码器 resolution=1024 决定（跟随参考图宽高比）；无独立宽高参数、无细化开/关开关（i2i 恒走 PE 细化）
- JSON 手术：JSON 里预置 10 个图槽，提交时**未提供的文件参数对应的图节点由服务自动摘除**（并清理消费节点的列表槽连线），等价于旧 edit_1..5 的按图数拆工作流
## 参数
- INPUT_PROMPT_TEXT   编辑提示词
- INPUT_NEGATIVE_PROMPT_TEXT   负面提示词（默认空）
- INPUT_IMAGE_1_FILE   **必须**：参考图1文件名（先经 comfyui_upload_file 上传再注入；JSON 里的默认图名仅占位，不传则报错）
- INPUT_IMAGE_2_FILE   可选：参考图2文件名（同上）
- INPUT_IMAGE_3_FILE   可选：参考图3文件名（同上）
- INPUT_IMAGE_4_FILE   可选：参考图4文件名（同上）
- INPUT_IMAGE_5_FILE   可选：参考图5文件名（同上）
- INPUT_IMAGE_6_FILE   可选：参考图6文件名（同上）
- INPUT_IMAGE_7_FILE   可选：参考图7文件名（同上）
- INPUT_IMAGE_8_FILE   可选：参考图8文件名（同上）
- INPUT_IMAGE_9_FILE   可选：参考图9文件名（同上）
- INPUT_IMAGE_10_FILE  可选：参考图10文件名（同上）

说明：
- 最多 10 张；文件参数须**从 INPUT_IMAGE_1_FILE 开始连续提供**（如传 3 张就是 1/2/3），缺号或漏掉图 1 会报明确错误
- 一张都不传会报「至少需要 1 张参考图」
- KSampler 种子固定 580553834379245、PE 内部种子固定 717769733027864（无种子参数节点）
- 输出图片尺寸遵守 INPUT_IMAGE_1_FILE 的尺寸（按 1024 分辨率档等比缩放；其余参考图只作语义参考，不影响输出尺寸）

## 预计时间
- 实测（mifengzhaopu，2026-10-10）：1 图 ≈30s、3 图 ≈35s、10 图 ≈95s（PE 阶段随图数线性变久，采样段固定）
## 输出文件的前缀
- {实例名}_qwen_image_21_edit_10（如 mifengzhaopu_qwen_image_21_edit_10；远端保存前缀 Qwen_Image_21_Edit）

## 所需节点（class_type，缺则执行报 Unknown node type）
- `LoadQwenImage21PEMTP`、`TextGenerateQwen35MTP`、`UNETLoader`、`QwenImage21Cache`、`CLIPLoader`、`VAELoader`、`TextEncodeQwenImage21`、`KSampler`、`VAEDecode`、`SaveImageAdvanced`、`LoadImage`、`Text Multiline`、`PreviewAny`
