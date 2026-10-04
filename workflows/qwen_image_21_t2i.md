# qwen_image_21_t2i

## 分类
- 文生图（Qwen-Image 2.1）
## 介绍
- 采用 Qwen-Image 2.1 模型（int8 量化 UNet + Qwen3-VL 8B 文本编码 + 2.1 VAE，euler/simple 25 步）
- 可开启提示词细化：内置 9B 模型将简短提示词重写为详细英文长描述（默认开）
- 可开启思考模式（默认关）
- 输出尺寸默认 1920×1080，可调

## 参数
- INPUT_PROMPT_TEXT   提示词
- INPUT_NEGATIVE_PROMPT_TEXT   负面提示词（默认空）
- INPUT_WIDTH_VALUE   宽度（默认 1920）
- INPUT_HEIGHT_VALUE  高度（默认 1080）
- INPUT_REFINE_PROMPT_BOOL_VALUE   提示词细化（默认开）
- INPUT_PROMPT_THINK_MODE_BOOL_VALUE   思考模式（默认关）
- INPUT_SEED_VALUE   随机种子（默认 42）
## 预计时间
- 约2分钟（实测 124s，newgoai 4090 含提示词细化+25 步 int8 量化；实际视实例负载而定）
## 输出文件的前缀
- qwen_image_21_文生图

## 所需节点（class_type，缺则执行报 Unknown node type）
- `SaveImageAdvanced`、`BOOLConstant`、`ImpactInt`、`Text Multiline`、`UNETLoader`、`TextEncodeQwenImage21`、`CLIPLoader`、`VAELoader`、`EmptyLatentImage`、`VAEDecode`、`KSampler`、`TextGenerate`、`PreviewAny`、`ComfySwitchNode`、`PrimitiveStringMultiline`、`QwenImage21Cache`
