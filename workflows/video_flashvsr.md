# video_flashvsr

## 分类
- 视频高清2倍
## 介绍
- 采用flashvsr模型把原视频高清2倍，能细化环境与人物细节

## 参数
- INPUT_VIDEO_FILE   视频文件名
## 预计时间
- 2分钟(生成5秒视频)
## 输出文件的前缀
- flashvsr
## 多文件输出
- 生成一个mp4视频文件，是原视频尺寸的2倍

## 所需节点（class_type，缺则执行报 Unknown node type）
- `VHS_VideoCombine`、`VHS_VideoInfo`、`FlashVSRNode`、`VHS_LoadVideo`
