# qwen_camera_control

## 分类
- 图生图（多机位视角控制）
## 介绍
- 基于 QwenImageEditPlus 的多机位/多角度图像生成

- 传入底图文件名（先调 `comfyui_upload_file` 上传），通过水平角、垂直角、缩放参数控制相机视角

## 参数
- INPUT_IMAGE_FILE   底图文件名
- INPUT_H_ANGLE_VALUE      水平角度
- INPUT_V_ANGLE_VALUE      垂直角度
- INPUT_ZOOM_VALUE         缩放系数
## 所需节点（class_type）
- VAEDecode、VAELoader、UNETLoader、CLIPLoader、CFGNorm、KSampler、ModelSamplingAuraFlow、TextEncodeQwenImageEditPlus、FluxKontextMultiReferenceLatentMethod、LoraLoaderModelOnly、ImageScaleToTotalPixels、VAEEncode、QwenMultiangleCameraNode、SaveImage、LoadImage、INTConstant、Float
## 输出文件的前缀
- （以 SaveImage 保存的节点标题为准）
