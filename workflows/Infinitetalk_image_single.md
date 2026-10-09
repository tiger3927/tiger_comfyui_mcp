# Infinitetalk_image_single

## 分类
- 单图人物说话配音（1人说话）
## 介绍
- 只能给一个人配音

- 可以指定给画面中的谁配音,以及有什么行为描述

## 参数
- INPUT_PROMPT_TEXT   提示词
- INPUT_WIDTH_VALUE   宽度
- INPUT_HEIGHT_VALUE  高度
- INPUT_FPS_VALUE  帧率，默认24
- INPUT_SECONDS_VALUE       视频时长秒数，应小于低于声音长度
- INPUT_AUDIO_FILE   声音文件名
- INPUT_IMAGE_FILE   图像文件名
## 预计时间
- 3分钟(生成5秒视频)
## 输出文件的前缀
- wan2_1_talk

## 多文件输出
- 生成一个mp4视频文件（带声音）
- 生成一个该视频的尾帧图像

## 所需节点（class_type，缺则执行报 Unknown node type）
- `MultiTalkModelLoader`、`WanVideoModelLoader`、`WanVideoSampler`、`WanVideoVAELoader`、`WanVideoDecode`、`VHS_VideoCombine`、`WanVideoBlockSwap`、`WanVideoTextEncode`、`LoadWanVideoT5TextEncoder`、`DownloadAndLoadWav2VecModel`、`AudioCrop`、`ImageResizeKJv2`、`CLIPVisionLoader`、`WanVideoTorchCompileSettings`、`WanVideoImageToVideoMultiTalk`、`WanVideoClipVisionEncode`、`MultiTalkWav2VecEmbeds`、`INTConstant`、`FloatConstant`、`MathExpression|pysssss`、`StringConcatenate`、`CR Integer To String`、`ConsoleDebug+`、`Text Multiline`、`GoogleTranslateTextNode`、`GetImageRangeFromBatch`、`SaveImage`、`ImageColorMatch+`、`WanVideoLoraSelectMulti`、`MelBandRoFormerSampler`、`MelBandRoFormerModelLoader`、`LoadAudio`、`LoadImage`
