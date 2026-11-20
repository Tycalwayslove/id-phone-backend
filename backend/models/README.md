# 图像处理模型

模型文件不进 Git，用 `uv run python -m scripts.download_models` 下载（带 sha256 校验）。决策见 `docs/adr/0007-in-house-photo-pipeline.md`。

| 文件 | 用途 | 来源 | 许可证 |
|---|---|---|---|
| `modnet_photographic_portrait_matting.onnx`（约 25MB） | 人像抠图 | [MODNet](https://github.com/ZHKKKe/MODNet) 官方权重，ONNX 由 [HivisionIDPhotos](https://github.com/Zeyi-Lin/HivisionIDPhotos) 转换发布 | Apache-2.0（MODNet README：“The code, models, and demos … are released under the Apache License 2.0”） |
| `birefnet_portrait.onnx`（约 972MB） | 精细抠图默认模型（`FINE_MATTING_MODEL`），后台替换 MODNet 结果；只保留人，能去掉紧贴身后的椅子 | [BiRefNet](https://github.com/ZhengPeng7/BiRefNet) release v1 `BiRefNet-portrait-epoch_150` | MIT |
| `birefnet_general_swin_tiny.onnx`（约 224MB） | 通用轻量版，速度快一倍，但会把身后物体当前景；可通过 `FINE_MATTING_MODEL` 切换 | [BiRefNet](https://github.com/ZhengPeng7/BiRefNet) release v1 | MIT |
| `face_detection_yunet_2023mar.onnx`（约 230KB） | 人脸框与 5 个关键点 | [OpenCV Zoo YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) | MIT |

**不要使用**：BRIA RMBG-1.4 / RMBG-2.0（非商用许可，商用需另购授权）。HivisionIDPhotos 附带的 `hivision_modnet` 权重未单独声明许可，只可用于本地效果对比，不进生产。
