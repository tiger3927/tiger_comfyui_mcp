# qwen_image_edit_3

## 分类
- 图像编辑（3图）
## 介绍
- 采用RapidAIO-18模型

- 提示词用图1图2可混合编辑3张图，以图1为主图

## 参数
- INPUT_PROMPT_VALUE   提示词
- INPUT_IMAGE_1_FILE   图1文件名
- INPUT_IMAGE_2_FILE   图2文件名
- INPUT_IMAGE_3_FILE   图3文件名
- INPUT_SEED   随机种子（默认 42）
## 预计时间
- 20秒
## 输出文件的前缀
- qwen_image_edit

## 所需节点（class_type，缺则执行报 Unknown node type）
- `CLIPLoader`、`VAELoader`、`KSampler`、`VAEDecode`、`LoraLoaderModelOnly`、`ConditioningZeroOut`、`QwenEditConfigPreparer`、`PrimitiveStringMultiline`、`CropWithPadInfo`、`ImageScaleBy`、`QwenEditOutputExtractor`、`TextEncodeQwenImageEditPlusCustom_lrzjason`、`SaveImage`、`INTConstant`、`easy seed`、`UnetLoaderGGUF`、`LoadImage`
