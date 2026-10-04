# z_text_2_image_pose

## 分类
- 文生图（可以加人体姿态参考图）
## 介绍
- 可以设置参考姿势（需要传入参考图文件名）

- 可以设置添加胶片噪点同时细化图像
- 可以选择开启RedZImage模式（利于亚洲人像）

## 参数
- INPUT_PROMPT_TEXT   提示词
- INPUT_WIDTH_VALUE   宽度
- INPUT_HEIGHT_VALUE  高度
- INPUT_REDZIMAGE_BOOL_VALUE  使用RedZImage
- INPUT_POSE_BOOL_VALUE       使用姿势参考图
- INPUT_ADDNOISE_BOOL_VALUE   加噪点及放大细化
- INPUT_POSE_FILE   人物姿势参考图文件名
- INPUT_SEED   随机种子（默认 42）
## 预计时间
- 20秒
## 输出文件的前缀
- Z-Image文生图

## 所需节点（class_type，缺则执行报 Unknown node type）
- `CLIPTextEncode`、`UNETLoader`、`ConditioningZeroOut`、`KSampler`、`CLIPLoader`、`VAELoader`、`VAEDecode`、`EmptyLatentImage`、`ImpactInt`、`easy seed`、`CheckpointLoaderSimple`、`VAEEncode`、`ImageScaleBy`、`MathExpression|pysssss`、`easy compare`、`easy ifElse`、`SeedVR2ExtraArgs`、`SeedVR2BlockSwap`、`GetImageSize`、`LayerUtility: PurgeVRAM`、`SeedVR2`、`Image Comparer (rgthree)`、`SaveImage`、`Text Multiline`、`ImageResizeKJv2`、`ModelPatchLoader`、`QwenImageDiffsynthControlnet`、`AIO_Preprocessor`、`easy cleanGpuUsed`、`BOOLConstant`、`LoraLoaderModelOnly`、`LGNoiseInjectionLatent`、`GenerateNoise`、`LazySwitchKJ`、`EmptyImage`、`LoadImage`
