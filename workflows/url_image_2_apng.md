# url_image_2_apng
## 分类
- 图生图动效（URL 图片 → 动画 APNG）
## 介绍
- 传入图片 URL 与提示词，Wan 首尾帧模型生成短动效
- 输出 VHS_VideoCombine 视频与 SaveAnimatedPNG 动画（APNG）
## 参数
- INPUT_TEXT     提示词
- INPUT_URL      输入图片 URL
- 视频高度（Int "Video Height"）、视频时长秒（Int "Video length(in seconds)"）、FPS（FloatConstant）、MAX-WIDTH（Int）
## 所需节点（class_type，缺则执行报 Unknown node type）
- `PathchSageAttentionKJ`、`ModelPatchTorchSettings`、`UNETLoader`、`CLIPLoader`、`CLIPVisionLoader`、`INTConstant`、`SimpleMath+`、`ImageResizeKJv2`、`WanFirstLastFrameToVideo`、`CLIPVisionEncode`、`CLIPTextEncode`、`VAEDecode`、`easy cleanGpuUsed`、`VHS_VideoCombine`、`WanMoeKSampler`、`wanBlockSwap`、`VAELoader`、`Int`、`LoraLoaderModelOnly`、`Image Blank`、`ImageComposite+`、`MaskFromColor+`、`JoinImageWithAlpha`、`SaveAnimatedPNG`、`easy isMaskEmpty`、`LazySwitchKJ`、`FloatConstant`、`VHS_LoadImagePath`、`TY_UrlDownload`、`ShowText|pysssss`、`PreviewImage`、`MathExpression|pysssss`、`easy ifElse`、`easy compare`、`PreviewAny`、`GetImageSize+`
## 输出文件的前缀
- （VHS_VideoCombine / SaveAnimatedPNG 标题决定）
