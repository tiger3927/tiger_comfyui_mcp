# mmaudio_video_add_soundeffect

## 分类
- 视频配音效（不含说话声不含唱歌声）
## 介绍
- 只能给视频加上环境声和音效声，不包括人说话声和唱歌声

- 可以指定正向提示词，描述应该有什么声音
- 可以指定负向提示词，描述不应该有什么声音

## 参数
- INPUT_VIDEO_FILE   视频文件名
- INPUT_PROMPT_TEXT   正向提示词
- INPUT_NEGATIVE_PROMPT_TEXT   负向提示词
## 预计时间
- 1分钟(生成5秒视频)
## 输出文件的前缀
- mmaudio_video_add_soundeffect
## 多文件输出
- 生成一个mp3音频文件，时长和原视频一致

## 所需节点（class_type，缺则执行报 Unknown node type）
- `MMAudioModelLoader`、`MMAudioSampler`、`MMAudioFeatureUtilsLoader`、`VHS_VideoInfo`、`VHS_LoadVideo`、`SaveAudioMP3`、`Text Multiline`
