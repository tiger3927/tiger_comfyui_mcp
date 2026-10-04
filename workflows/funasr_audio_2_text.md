# funasr_audio_2_text

## 分类
- 语音识别（ASR）- 音频转文字

## 介绍

- 输入音频文件（先调 `comfyui_upload_file` 上传取文件名），进行语音识别
- 使用阿里 FunASR 模型进行语音识别，支持时间戳
- 通过 WebSocket 监听节点输出获取识别结果（非文件下载方式）
- 同时输出纯文本和带时间戳的 JSON 格式结果

## 参数
- INPUT_AUDIO_FILE   音频文件名（必填，先调 `comfyui_upload_file` 上传取文件名）

## 预计时间
- 10-30秒（取决于音频长度）

## 输出文件的前缀
- funasr_audio_2_text

## 多文件输出
- 输出一个txt文本文件，是识别的文字内容
- 输出一个json文件，是识别的文字内容，和每个字的时间戳

## 注意事项
1. 音频格式支持：wav、mp3 等常见格式（建议 wav 格式）

## 所需节点（class_type，缺则执行报 Unknown node type）
- `AVASRTimestamp`、`ShowText|pysssss`、`LoadAudio`
