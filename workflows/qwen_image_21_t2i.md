# qwen_image_21_t2i

## 分类
- 文生图（Qwen-Image 2.1）
## 介绍
- 采用 Qwen-Image 2.1 模型（int8 量化 UNet + Qwen3-VL 8B 文本编码 + 2.1 VAE，euler/simple 25 步）
- 提示词细化恒开：Qwen-Image 2.1 PE（MTP）增强器将简短提示词重写为详细描述，正面/负面提示词均取自增强器输出（简化版已删除细化开关与 LazySwitchKJ）
- 思考模式恒开（PE 增强器 preset.thinking 固定 true；简化版已删除思考开关节点）
- 输出尺寸默认 1920×1080，可调

## 参数
- INPUT_PROMPT_TEXT   提示词（默认值"大老虎！"；**固定种子下不注入此参数会重复出同一张图**）
- INPUT_WIDTH_VALUE   宽度（默认 1920）
- INPUT_HEIGHT_VALUE  高度（默认 1080）

说明：
- KSampler 随机种子为固定值 1081401478004198（未提供种子参数节点）；PE 增强器另有独立内部种子 42
- 负面提示词恒取自 PE 增强器输出（无独立负面提示词参数，简化版已删除 `INPUT_NEGATIVE_PROMPT_TEXT` 节点）
- PE 增强器为 llama.cpp 后端（模型 Q8_0 量化 + f16 全精度 KV 缓存），执行完自动卸载（unload_model）

## 预计时间
- 约20秒到30秒
## 输出文件的前缀
- Qwen_Image_21

## 所需节点（class_type，缺则执行报 Unknown node type）
- `LoadQwenImage21PEMTP`、`TextGenerateQwen35MTP`、`UNETLoader`、`CLIPLoader`、`VAELoader`、`TextEncodeQwenImage21`、`KSampler`、`VAEDecode`、`PreviewAny`、`EmptyLatentImage`、`SaveImageAdvanced`、`Text Multiline`、`ImpactInt`
