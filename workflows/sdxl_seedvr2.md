# sdxl_seedvr2

## 分类
- 图片提升质量
## 介绍
- SDXL模型增加图像人物皮肤头发的细节

- SeedVR2模型放大图像,尺寸乘以1.5放大

## 参数
- INPUT_IMAGE_FILE   原图文件名
- INPUT_SDXL_BOOL_VALUE   打开SDXL皮肤头发强化
## 预计时间
- 40秒
## 输出文件的前缀
- seedvr2_sdxl

## 所需节点（class_type，缺则执行报 Unknown node type）
- `easy ifElse`、`easy compare`、`MathExpression|pysssss`、`KSampler`、`GetImageSize`、`SeedVR2BlockSwap`、`SeedVR2ExtraArgs`、`SeedVR2`、`CLIPTextEncode`、`CheckpointLoaderSimple`、`VAEDecode`、`VAEEncode`、`ImageScaleBy`、`LayerUtility: PurgeVRAM`、`SaveImage`、`BOOLConstant`、`ImageResizeKJv2`、`easy seed`、`LazySwitchKJ`、`LoadImage`
