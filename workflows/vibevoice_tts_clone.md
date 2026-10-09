# vibevoice_tts_clone

## 分类
- 语音克隆（微软VibeVoice模型，单人）
## 介绍
- VibeVoice-1.5B 单说话人克隆，模型自主解析并发挥情绪
## 参数
- INPUT_TALK_TEXT   说话稿
- INPUT_AUDIO_FILE   克隆参考音频文件名
- INPUT_TEMPERATURE_VALUE 温度（默认0.5）
## 预计时间
- 30秒（生成10秒音频）
## 输出文件的前缀
- vibevoice
## 输出文件
- 一个mp3音频文件

## 所需节点（class_type，缺则执行报 Unknown node type）
- `VibeVoiceSingleSpeakerNode`、`Text Multiline`、`LoadAudio`、`Float`、`SaveAudioAdvanced`
