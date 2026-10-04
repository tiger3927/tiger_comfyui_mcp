# fl_image_smoothmix_video

## 分类

- 首尾帧图生视频（smoothmix模型，动感已加强）

## 介绍

- 比原版wan2.2动感加强，用了奖励lora
- 同时设置首尾帧

## 参数

- INPUT_PROMPT_TEXT   提示词
- INPUT_NEGATIVE_PROMPT_TEXT   负向提示词
- INPUT_WIDTH_VALUE   宽度
- INPUT_HEIGHT_VALUE  高度
- INPUT_FIRST_IMAGE_FILE   首帧图文件名
- INPUT_LAST_IMAGE_FILE   尾帧图文件名
- INPUT_SECONDS_VALUE  视频长度秒数

## 预计时间

- 3分钟(生成5秒视频)

## 输出文件的前缀
- SmoothMix_FL

## 多文件输出
- 输出一个mp4视频文件（静音）
- 输出该视频的尾帧图像

## 所需节点（class_type，缺则执行报 Unknown node type）
- `PathchSageAttentionKJ`、`ModelPatchTorchSettings`、`UNETLoader`、`CLIPLoader`、`CLIPVisionLoader`、`INTConstant`、`SimpleMath+`、`ImageResizeKJv2`、`WanFirstLastFrameToVideo`、`CLIPVisionEncode`、`CLIPTextEncode`、`VAEDecode`、`easy cleanGpuUsed`、`VHS_VideoCombine`、`WanMoeKSampler`、`wanBlockSwap`、`VAELoader`、`Int`、`LoraLoaderModelOnly`、`LoadImage`、`GetImageRangeFromBatch`、`SaveImage`
