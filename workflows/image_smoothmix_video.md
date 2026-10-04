# image_smoothmix_video

## 分类
- 图生视频（smoothmix模型，动感加强）
## 介绍
- 比原版wan2.2动感加强，用了奖励lora

- 只能设置首帧图

## 参数
- INPUT_PROMPT_TEXT   提示词
- INPUT_NEGATIVE_PROMPT_TEXT   负向提示词
- INPUT_WIDTH_VALUE   宽度
- INPUT_HEIGHT_VALUE  高度
- INPUT_IMAGE_FILE   首帧图文件名
- INPUT_SECONDS_VALUE  视频长度秒数
## 预计时间
- 2分钟(生成5秒视频)
## 输出文件的前缀
- SmoothMix

## 多文件输出
- 输出一个mp4后缀的视频文件（静音）
- 输出一个该视频尾帧图像

## 所需节点（class_type，缺则执行报 Unknown node type）
- `CLIPTextEncode`、`VAEDecode`、`PathchSageAttentionKJ`、`ModelPatchTorchSettings`、`UNETLoader`、`CLIPLoader`、`CLIPVisionLoader`、`CLIPVisionEncode`、`SimpleMath+`、`easy cleanGpuUsed`、`WanMoeKSampler`、`WanImageToVideo`、`ImageResizeKJv2`、`VHS_VideoCombine`、`INTConstant`、`wanBlockSwap`、`VAELoader`、`Int`、`easy seed`、`LoraLoaderModelOnly`、`LoadImage`、`GetImageRangeFromBatch`、`SaveImage`
