# ltx23_image_talking

## 分类
- 单图作为首帧，人物说话和唱歌配音配口型（1人说话）
## 介绍
- 只能给一个人配音

- 可以指定给画面中的谁配音,以及行为描述，场景变化描述

## 参数
- INPUT_PROMPT_TEXT   提示词
- INPUT_WIDTH_VALUE   宽度
- INPUT_HEIGHT_VALUE  高度
- INPUT_FPS_VALUE  帧率，默认16
- INPUT_AUDIO_FILE   声音文件名
- INPUT_IMAGE_FILE   图像文件名
- INPUT_SECONDS_VALUE  视频时长秒数，应小于低于声音长度
## 预计时间
- 5分钟(生成15秒视频)
## 输出文件的前缀
- ltx_23_i2v_talking

## 多文件输出
- 1个视频文件（带声音）
- 1个该视频的尾帧图像

## 所需节点（class_type，缺则执行报 Unknown node type）
- `LTXVScheduler`、`ManualSigmas`、`LatentUpscaleModelLoader`、`LTXVCropGuides`、`CFGGuider`、`ImageScaleBy`、`GetImageSize`、`LTXVConditioning`、`EmptyLTXVLatentVideo`、`LTXVConcatAVLatent`、`CLIPTextEncode`、`EmptyImage`、`SamplerCustomAdvanced`、`RandomNoise`、`LTXVSeparateAVLatent`、`LTXVLatentUpsampler`、`VAEDecodeTiled`、`LoraLoaderModelOnly`、`KSamplerSelect`、`CheckpointLoaderSimple`、`LTXAVTextEncoderLoader`、`VAELoader`、`LTXVImgToVideoInplace`、`LTXVPreprocess`、`ImageResizeKJv2`、`ImpactExecutionOrderController`、`VHS_VideoCombine`、`MelBandRoFormerModelLoader`、`SolidMask`、`LTXVAudioVAEEncode`、`SetLatentNoiseMask`、`MelBandRoFormerSampler`、`ShowAnything|Mie`、`PrimitiveFloat`、`Audio Duration (mtb)`、`Text Multiline`、`LoadImage`、`LoadAudio`、`INTConstant`、`VAELoaderKJ`、`SimpleCalculatorKJ`、`GetImageRangeFromBatch`、`SaveImage`、`AudioCrop`、`CR Integer To String`、`StringConcatenate`、`MathExpression|pysssss`、`FloatConstant`
