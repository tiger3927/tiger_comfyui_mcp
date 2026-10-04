# qwen3_tts_clone

## 分类
- 语音克隆（qwen3-tts模型）
## 介绍
- 中规中矩，正常水平

## 参数
- INPUT_SPEAK_TEXT  说话稿文字
- INPUT_AUDIO_FILE   克隆参考音频文件名
## 预计时间
- 30秒（生成10秒音频）
## 输出文件的前缀
- qwen3_tts_clone
## 输出文件
- 一个mp3音频文件

## 所需节点（class_type，缺则执行报 Unknown node type）
- `AILab_Qwen3TTSVoiceClone_Advanced`、`AILab_Qwen3TTSWhisperSTT`、`Text Multiline`、`LoadAudio`、`SaveAudioMP3`
