# hello
## 分类
- 文生图（SD1.5，冒烟/联调用）
## 介绍
- 最小文生图链路：检查点 + 双提示词 + 采样 + 保存
- 用于服务联调冒烟（新实例接入后先跑这个验证全链路）
## 参数
- INPUT_POSITIVE_TEXT  正向提示词
- INPUT_NEGATIVE_TEXT  负向提示词
- ckpt_name            检查点（注意：默认 SD 1.5 primemix 仅原参考工程服务器有，其他实例需注入可用模型，见 object_info CheckpointLoaderSimple.ckpt_name）
- seed / steps / cfg / width / height  采样参数（KSampler / EmptyLatentImage）
## 所需节点（class_type，缺则执行报 Unknown node type）
- `KSampler`、`CheckpointLoaderSimple`、`EmptyLatentImage`、`CLIPTextEncode`、`VAEDecode`、`SaveImage`
## 预计时间
- 30~60 秒（SD1.5 512×512 20 步）
## 输出文件的前缀
- ComfyUI（保存节点默认标题）
