"""为拍后检测和光影校正取样，并估计前景白平衡。"""

import cv2
import numpy as np
from PIL import Image

from app.modules.photos.pipeline.face import Face

_MAX_FACE_B_DROP = 2.0  # CIELAB b* 单位


def _sample(image: Image.Image, box: tuple[float, float, float, float]) -> np.ndarray:
    left = max(0, round(box[0]))
    top = max(0, round(box[1]))
    right = min(image.width, round(box[2]))
    bottom = min(image.height, round(box[3]))
    if left >= right or top >= bottom:
        return np.empty((0, 3), dtype=np.uint8)
    sample = image.crop((left, top, right, bottom))
    sample.thumbnail((128, 128), Image.Resampling.BOX)
    pixels = np.asarray(sample)
    if image.mode == "RGBA":
        return pixels[pixels[:, :, 3] > 127, :3]
    return pixels.reshape(-1, 3)


def cheek_samples(image: Image.Image, face: Face) -> tuple[np.ndarray, np.ndarray]:
    """取鼻尖下方附近两侧脸颊，避开鼻子、眼睛和嘴。"""
    center = face.center_x
    width, height = face.width, face.height
    top = face.y + 0.48 * height
    bottom = face.y + 0.68 * height
    return (
        _sample(image, (center - 0.32 * width, top, center - 0.11 * width, bottom)),
        _sample(image, (center + 0.11 * width, top, center + 0.32 * width, bottom)),
    )


def portrait_sample(image: Image.Image) -> np.ndarray:
    if image.mode == "RGBA":
        return _sample(image, (0, 0, image.width, image.height))
    return _sample(image, (0.2 * image.width, 0.15 * image.height, 0.8 * image.width, 0.85 * image.height))


def luminance(pixels: np.ndarray) -> float:
    return float(cv2.cvtColor(pixels.reshape(-1, 1, 3), cv2.COLOR_RGB2GRAY).mean())


def _midtone_foreground(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    # 直接按像素取样，避免缩图混入蒙版外的颜色或把极端亮度平均为中间调。
    step = max(1, max(alpha.shape) // 128)
    pixels = rgb[::step, ::step][alpha[::step, ::step] > 127]
    if not pixels.size:
        return pixels
    gray = cv2.cvtColor(pixels[:, None, :], cv2.COLOR_RGB2GRAY).ravel()
    return pixels[(gray >= 32) & (gray <= 235)]


def _mean_lab_b(rgb: np.ndarray) -> float:
    return float(cv2.cvtColor(rgb[:, None, :], cv2.COLOR_RGB2LAB)[:, 0, 2].mean())


def white_balance_gains(rgb: np.ndarray, alpha: np.ndarray | None, face: Face | None) -> np.ndarray:
    """用前景中间调估计白平衡，并限制脸部暖色的损失。"""
    neutral = np.ones(3, dtype=np.float32)
    if alpha is None:
        return neutral
    sample = _midtone_foreground(rgb, alpha)
    if not sample.size:
        return neutral

    means = sample.mean(axis=0, dtype=np.float32)
    gains = np.clip(1 + 0.16 * (means.mean() / np.maximum(means, 1) - 1), 0.9, 1.1)
    if face is None:
        return gains

    left, top = max(0, round(face.x)), max(0, round(face.y))
    right = min(rgb.shape[1], round(face.x + face.width))
    bottom = min(rgb.shape[0], round(face.y + face.height))
    if left >= right or top >= bottom:
        return neutral
    face_sample = _midtone_foreground(rgb[top:bottom, left:right], alpha[top:bottom, left:right])
    if not face_sample.size:
        return neutral
    face_rgb = face_sample.astype(np.float32) / 255
    drop = _mean_lab_b(face_rgb) - _mean_lab_b(np.clip(face_rgb * gains, 0, 1))
    if drop > _MAX_FACE_B_DROP:
        gains = 1 + (gains - 1) * (_MAX_FACE_B_DROP / drop)
    return gains
