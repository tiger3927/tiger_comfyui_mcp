# wan22_sviv2_video_continue

## 分类
- 视频接力生视频
## 介绍
- wan2.2的SVI-V2lora，接着上一段视频生成一致性角色视频

- 传入角色带场景图、上一段视频，接力生成，5秒一段

## 参数
- INPUT_IMAGE_FILE   角色带场景原图文件名（必须）
- INPUT_LAST_VIDEO_FILE   上一段视频文件名
- INPUT_PROMPT_TEXT  提示词（必须）
## 预计时间
- 3分钟(生成5秒视频)
## 输出文件的前缀
- 一个mp4视频文件，以Wan22-SVI-V2开头
- 一个该视频的尾帧图像，以Wan22-SVI-V2开头

## 所需节点（class_type，缺则执行报 Unknown node type）
- `CLIPLoader`、`VAELoader`、`DiffusionModelLoaderKJ`、`SplitSigmas`、`ImageResizeKJv2`、`VAEEncode`、`ModelSamplingSD3`、`BasicScheduler`、`KSamplerSelect`、`LoraLoaderModelOnly`、`VHS_VideoCombine`、`DisableNoise`、`ScheduledCFGGuidance`、`RandomNoise`、`CLIPTextEncode`、`VAEDecode`、`SamplerCustomAdvanced`、`ImageBatchExtendWithOverlap`、`WanImageToVideoSVIPro`、`INTConstant`、`easy mathInt`、`Text Multiline`、`VHS_LoadVideo`、`VHS_VideoInfo`、`LoadImage`、`SaveImage`、`GetImageRangeFromBatch`
