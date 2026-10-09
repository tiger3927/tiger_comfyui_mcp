# qwen_image_21_edit_4

## 分类
- 图像编辑（Qwen-Image 2.1，4 张参考图）
## 介绍
- 采用 Qwen-Image 2.1 模型（int8 量化 UNet + Qwen3-VL 8B 文本编码 + 2.1 VAE，euler/simple 25 步）
- i2i 编辑模式：4 张参考图 + 编辑提示词；PE（MTP）增强器（i2i preset、思考恒开）结合参考图生成正面/负面提示与图像条件 latent
- 输出分辨率由编码器 resolution=1024 决定（跟随参考图宽高比）；无独立宽高参数、无细化开/关开关（i2i 恒走 PE 细化）
## 参数
- INPUT_PROMPT_TEXT   编辑提示词
- INPUT_NEGATIVE_PROMPT_TEXT   负面提示词（默认空）
- INPUT_IMAGE_1_FILE   参考图1文件名（先经 comfyui_upload_file 上传再注入；JSON 里的默认图名仅占位，不上传则执行报文件缺失）
- INPUT_IMAGE_2_FILE   参考图2文件名（同上）
- INPUT_IMAGE_3_FILE   参考图3文件名（同上）
- INPUT_IMAGE_4_FILE   参考图4文件名（同上）

说明：KSampler 种子固定 880703448599808、PE 内部种子固定 186994430569163（无种子参数节点）
- 输出图片尺寸以输入图 1 的分辨率为准（按 1024 分辨率档等比缩放；其余参考图只作语义参考，不影响输出尺寸；实测方形参考图 → 输出 1024×1024）

## 预计时间
- 40s
## 输出文件的前缀
- {实例名}_qwen_image_21_edit_4（如 newgoai_qwen_image_21_edit_4；远端保存前缀 Qwen_Image_21_Edit）

## 所需节点（class_type，缺则执行报 Unknown node type）
- `LoadQwenImage21PEMTP`、`TextGenerateQwen35MTP`、`UNETLoader`、`QwenImage21Cache`、`CLIPLoader`、`VAELoader`、`TextEncodeQwenImage21`、`KSampler`、`VAEDecode`、`SaveImageAdvanced`、`LoadImage`、`Text Multiline`、`PreviewAny`
