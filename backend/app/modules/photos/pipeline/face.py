"""用 YuNet 检测人脸。坐标以纠正方向后的原图为准。"""

from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import cv2
import numpy as np
from PIL import Image

from app.core.config import settings

YUNET_MODEL = "face_detection_yunet_2023mar.onnx"
FACE_SCORE_THRESHOLD = 0.85
DETECTION_MAX_SIDE = 960

type Point = tuple[float, float]


@dataclass(frozen=True)
class Face:
    x: float
    y: float
    width: float
    height: float
    # YuNet 顺序：右眼、左眼、鼻尖、右嘴角、左嘴角（以被拍摄者为准）。
    landmarks: tuple[Point, Point, Point, Point, Point]
    confidence: float

    @property
    def center_x(self) -> float:
        return (self.landmarks[0][0] + self.landmarks[1][0]) / 2

    def in_viewport(self, left: float, top: float, scale: float) -> Face:
        return Face(
            (self.x - left) * scale,
            (self.y - top) * scale,
            self.width * scale,
            self.height * scale,
            tuple(((x - left) * scale, (y - top) * scale) for x, y in self.landmarks),
            self.confidence,
        )


_lock = Lock()
_detector: cv2.FaceDetectorYN | None = None
_model_path: Path | None = None


def detect_faces(image: Image.Image) -> list[Face]:
    """返回达到置信度阈值的人脸，按置信度降序排列。"""
    global _detector, _model_path
    width, height = image.size
    scale = min(1.0, DETECTION_MAX_SIDE / max(image.size))
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    resized = image.resize(size, Image.Resampling.BILINEAR) if size != image.size else image
    rgb = resized.convert("RGB")
    if resized.mode == "RGBA":
        rgb = Image.composite(rgb, Image.new("RGB", size, (127, 127, 127)), resized.getchannel("A"))
    bgr = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
    path = settings.photo_models_dir / YUNET_MODEL
    # YuNet 的输入尺寸写在实例上，与推理一起持锁，避免并发请求覆盖尺寸。
    with _lock:
        if _detector is None or _model_path != path:
            if not path.is_file():
                raise FileNotFoundError(
                    f"缺少人脸检测模型 {YUNET_MODEL}，请在 backend 目录运行 uv run python -m scripts.download_models"
                )
            _detector = cv2.FaceDetectorYN.create(str(path), "", size, FACE_SCORE_THRESHOLD, 0.3, 5000)
            _model_path = path
        _detector.setInputSize(size)
        _, rows = _detector.detect(bgr)

    faces = []
    if rows is not None:
        scale_x, scale_y = width / size[0], height / size[1]
        for row in rows:
            confidence = float(row[14])
            if not np.isfinite(row).all() or confidence < FACE_SCORE_THRESHOLD:
                continue
            x, y, w, h = map(float, row[:4])
            if w <= 0 or h <= 0:
                continue
            points = tuple((float(px) * scale_x, float(py) * scale_y) for px, py in row[4:14].reshape(5, 2))
            faces.append(Face(x * scale_x, y * scale_y, w * scale_x, h * scale_y, points, confidence))
    return sorted(faces, key=lambda face: face.confidence, reverse=True)
