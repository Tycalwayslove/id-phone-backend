"""下载图像处理模型到 backend/models/（不进 Git）。部署和本机首次运行前执行：

    uv run python -m scripts.download_models

已存在且校验通过的文件会跳过。模型来源与许可证见 models/README.md。
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"

# 文件名: (下载地址, sha256)
MODELS = {
    # MODNet 官方人像抠图权重（Apache-2.0），HivisionIDPhotos 转成的 ONNX
    "modnet_photographic_portrait_matting.onnx": (
        "https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/pretrained-model/modnet_photographic_portrait_matting.onnx",
        "07c308cf0fc7e6e8b2065a12ed7fc07e1de8febb7dc7839d7b7f15dd66584df9",
    ),
    # BiRefNet 人像版（MIT），精细抠图默认模型：只保留人，能去掉紧贴身后的椅子等；约 972MB，CPU 约 12 秒/张
    "birefnet_portrait.onnx": (
        "https://github.com/ZhengPeng7/BiRefNet/releases/download/v1/BiRefNet-portrait-epoch_150.onnx",
        "1ba1c8ff5a7bbfadc8d8d13fb11d7be793f91f23d9d466549e37a854f6668f99",
    ),
    # BiRefNet 通用分割 swin_v1_tiny（MIT），复杂背景下的精细抠图，CPU 约 5~8 秒/张，后台运行
    "birefnet_general_swin_tiny.onnx": (
        "https://github.com/ZhengPeng7/BiRefNet/releases/download/v1/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx",
        "5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333",
    ),
    # OpenCV Zoo 的 YuNet 人脸检测（MIT），输出人脸框和 5 个关键点
    "face_detection_yunet_2023mar.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    MODELS_DIR.mkdir(exist_ok=True)
    failed = False
    for name, (url, digest) in MODELS.items():
        path = MODELS_DIR / name
        if path.exists() and _sha256(path) == digest:
            print(f"已存在：{name}")
            continue
        print(f"下载：{name}")
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)  # 固定的 https 地址，下载后校验 sha256
        if _sha256(tmp) != digest:
            tmp.unlink()
            print(f"校验失败：{name}", file=sys.stderr)
            failed = True
            continue
        tmp.replace(path)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
