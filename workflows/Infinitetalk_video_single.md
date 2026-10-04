# Infinitetalk_video_single

## 分类
- 视频人物说话配音（1人说话）
## 介绍
- 只能给一个人配音

- 可以指定给视频画面中的谁配音,以及有什么行为描述

## 参数
- INPUT_AUDIO_FILE   声音文件名
- INPUT_VIDEO_FILE   视频文件名
- INPUT_PROMPT_TEXT   提示词
- INPUT_WIDTH_VALUE   宽度
- INPUT_HEIGHT_VALUE  高度
## 预计时间
- 3分钟(生成5秒视频)
## 输出文件的前缀
- Wan21_infinite_video_talk
## 多文件输出
- 生成一个mp4视频文件（带声音）
- 生成一个该视频的尾帧图像

## 所需节点（class_type，缺则执行报 Unknown node type）
- `MultiTalkModelLoader`、`WanVideoModelLoader`、`WanVideoSampler`、`WanVideoVAELoader`、`WanVideoDecode`、`VHS_VideoCombine`、`WanVideoBlockSwap`、`WanVideoTextEncode`、`LoadWanVideoT5TextEncoder`、`DownloadAndLoadWav2VecModel`、`WanVideoLoraSelect`、`AudioCrop`、`AudioSeparation`、`CLIPVisionLoader`、`WanVideoTorchCompileSettings`、`WanVideoImageToVideoMultiTalk`、`WanVideoClipVisionEncode`、`MultiTalkWav2VecEmbeds`、`INTConstant`、`VHS_VideoInfo`、`MathExpression|pysssss`、`StringConcatenate`、`CR Integer To String`、`GetImageRangeFromBatch`、`WanVideoEncode`、`ImageResizeKJv2`、`MelBandRoFormerModelLoader`、`MelBandRoFormerSampler`、`Text Multiline (Code Compatible)`、`VHS_LoadVideo`、`LoadAudio`、`Audio Duration (mtb)`、`ShowAnything|Mie`、`SaveImage`
