# qwen3_tts_design
## 分类
- 按需设计语音音色（qwen3-tts模型）
## 介绍
- 可自主设计角色音色，带情绪等丰富描述，常用来生成语音克隆的参考音
## 参数
- INPUT_SPEAK_TEXT  说话稿文字
- INPUT_DESIGN_TEXT   音色描述文字
## 预计时间
- 20秒（生成10秒音频）
## 输出文件的前缀
- qwen3_tts_design
## 输出文件
- 一个mp3音频文件

## 所需节点（class_type，缺则执行报 Unknown node type）
- `AILab_Qwen3TTSVoiceDesign_Advanced`、`Text Multiline`、`SaveAudioMP3`
