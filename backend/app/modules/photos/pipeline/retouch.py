"""只调整像素颜色和局部纹理，保留原有位置与透明通道。"""

from collections.abc import Sequence

import cv2
import numpy as np
from PIL import Image

from app.modules.photos.pipeline.face import Face, Point
from app.modules.photos.pipeline.lighting import (
    cheek_samples,
    luminance,
    portrait_sample,
    white_balance_gains,
)


def _automatic_light(image: Image.Image, face: Face | None, alpha: np.ndarray | None) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB"))
    left, right = cheek_samples(image, face) if face is not None else (None, None)
    has_cheeks = left is not None and right is not None and left.size > 0 and right.size > 0
    sample = np.concatenate((left, right)) if has_cheeks else portrait_sample(image)
    if not sample.size:
        return rgb

    balance = white_balance_gains(rgb, alpha, face)
    exposure = luminance(sample)
    gain = np.clip(np.clip(exposure, 118, 172) / max(exposure, 1), 0.86, 1.18)
    adjusted = rgb.astype(np.float32) * (balance * gain).astype(np.float32)

    if has_cheeks:
        difference = luminance(right) - luminance(left)
        # 左侧较暗时提亮左侧并压低右侧，修正幅度在脸中线及脸外平滑衰减。
        x = (np.arange(image.width, dtype=np.float32) - face.center_x) / face.width
        y = (np.arange(image.height, dtype=np.float32) - face.y - face.height / 2) / face.height
        taper = np.exp(-2.0 * (x**2 + y[:, None] ** 2))
        # 每侧最多修正四分之一的亮度差，因此总修正不超过一半。
        shift = -np.clip(difference * gain / 4, -20, 20) * np.clip(x * 5, -1, 1) * taper
        adjusted += shift[:, :, None]

    return np.rint(np.clip(adjusted, 0, 255)).astype(np.uint8)


def _guided_smooth(rgb: np.ndarray, radius: int) -> np.ndarray:
    source = rgb.astype(np.float32) / 255
    guide = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY)
    size = (2 * radius + 1, 2 * radius + 1)
    mean_g = cv2.boxFilter(guide, -1, size)
    mean_rgb = cv2.boxFilter(source, -1, size)
    variance = cv2.boxFilter(guide * guide, -1, size) - mean_g**2
    covariance = cv2.boxFilter(source * guide[:, :, None], -1, size) - mean_rgb * mean_g[:, :, None]
    slope = covariance / (variance[:, :, None] + 0.0025)
    intercept = mean_rgb - slope * mean_g[:, :, None]
    filtered = cv2.boxFilter(slope, -1, size) * guide[:, :, None] + cv2.boxFilter(intercept, -1, size)
    return np.rint(np.clip(filtered, 0, 1) * 255).astype(np.uint8)


def _ellipse(mask: np.ndarray, center: Point, face: Face, radius_x: float, radius_y: float) -> None:
    cv2.ellipse(
        mask,
        tuple(round(value) for value in center),
        (max(1, round(face.width * radius_x)), max(1, round(face.height * radius_y))),
        0,
        0,
        360,
        255,
        -1,
    )


def _beautify(rgb: np.ndarray, alpha: np.ndarray | None, face: Face, level: int) -> np.ndarray:
    oval = np.zeros(rgb.shape[:2], dtype=np.uint8)
    _ellipse(oval, (face.x + face.width / 2, face.y + face.height * 0.47), face, 0.56, 0.60)
    ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    skin = cv2.inRange(ycrcb, (0, 130, 75), (255, 180, 135))
    mask = cv2.bitwise_and(oval, skin)

    protect = np.zeros_like(mask)
    right_eye, left_eye, nose, right_mouth, left_mouth = face.landmarks
    for x, y in (right_eye, left_eye):
        _ellipse(protect, (x, y - 0.025 * face.height), face, 0.15, 0.105)
    _ellipse(protect, nose, face, 0.125, 0.105)
    mouth = ((right_mouth[0] + left_mouth[0]) / 2, (right_mouth[1] + left_mouth[1]) / 2)
    mouth_width = abs(left_mouth[0] - right_mouth[0]) / 2 + face.width * 0.07
    _ellipse(protect, mouth, face, mouth_width / face.width, 0.12)
    mask[protect != 0] = 0

    feather = max(1.0, face.width * 0.018)
    blend = cv2.GaussianBlur(mask.astype(np.float32) / 255, (0, 0), feather)
    feature_weight = 1 - cv2.GaussianBlur(protect.astype(np.float32) / 255, (0, 0), feather)
    blend *= feature_weight
    blend[protect != 0] = 0
    if alpha is not None:
        blend *= (alpha / 255) ** 2

    strength = level / 5
    smooth = _guided_smooth(rgb, max(1, round(face.width * 0.022)))
    lab = cv2.cvtColor(smooth, cv2.COLOR_RGB2LAB).astype(np.int16)
    # 混合权重随档位线性递增，限制肤色与亮度的最大变化。
    lab[:, :, 0] += 8
    lab[:, :, 2] -= 5
    toned = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)
    weight = blend[:, :, None] * (0.55 * strength)
    return np.rint(rgb + (toned.astype(np.float32) - rgb) * weight).astype(np.uint8)


def _inpaint(
    rgb: np.ndarray, alpha: np.ndarray | None, face: Face | None, blemishes: Sequence[Point]
) -> np.ndarray:
    height, width = rgb.shape[:2]
    face_width = face.width if face is not None else 0.55 * width
    radius = max(1, round(0.015 * face_width))
    mask = np.zeros((height, width), dtype=np.uint8)
    for x, y in blemishes:
        cv2.circle(mask, (round(x * (width - 1)), round(y * (height - 1))), radius, 255, -1)
    if alpha is not None:
        mask[alpha <= 127] = 0
    return cv2.inpaint(rgb, mask, radius, cv2.INPAINT_TELEA) if mask.any() else rgb


def retouch(
    image: Image.Image,
    face: Face | None,
    *,
    beauty_level: int = 0,
    blemishes: Sequence[Point] = (),
    has_foreground_mask: bool = True,
) -> Image.Image:
    """统一校正光影，再按档位精修皮肤并修补用户点选的痘印。"""
    alpha = image.getchannel("A") if image.mode == "RGBA" else None
    alpha_values = np.asarray(alpha) if alpha is not None else None
    # 原图裁剪时也可能生成仅标记取景边界的透明通道，白平衡只使用人像蒙版。
    rgb = _automatic_light(image, face, alpha_values if has_foreground_mask else None)
    if face is not None and beauty_level > 0:
        rgb = _beautify(rgb, alpha_values, face, beauty_level)
    if blemishes:
        rgb = _inpaint(rgb, alpha_values, face, blemishes)
    result = Image.fromarray(rgb)
    if alpha is not None:
        result.putalpha(alpha)
    return result
