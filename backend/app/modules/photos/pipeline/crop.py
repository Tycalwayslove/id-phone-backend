"""计算证件照取景框和裁剪后的关键点位置。"""

from math import ceil

import numpy as np
from PIL import Image

from app.modules.photos.pipeline.face import Face

# T024 通用证件照构图。头高占成品 55%～70%，以 62% 为目标。
HEAD_HEIGHT_RATIO = 0.62
MAX_HEAD_HEIGHT_RATIO = 0.70
HEADROOM_RATIO = 0.08


def _head_top(face: Face, alpha: Image.Image | None) -> float:
    if alpha is not None:
        left, right = max(0, round(face.x)), min(alpha.width, round(face.x + face.width))
        bottom = min(alpha.height, round(face.y))
        top = max(0, round(face.y - face.height))
        if right > left and bottom > top:
            rows = np.asarray(alpha.crop((left, top, right, bottom)))
            # 排除远离头部的蒙版碎点。
            present = np.flatnonzero((rows > 127).sum(axis=1) >= max(1, round((right - left) * 0.08)))
            if present.size:
                return top + int(present[0])
    # 原图没有可用蒙版时按人脸框估算发顶。
    return max(0.0, face.y - 0.20 * face.height)


def _fade_bottom(result: Image.Image, source_bottom: float, chin: float) -> None:
    # EXTENT 以像素中心采样，找到第一行落在原图下沿之外的位置。
    seam = ceil(source_bottom - 0.5)
    rows = min(3, seam - max(0, ceil(chin - 0.5)))
    if rows <= 0 or seam >= result.height:
        return

    # 仅取下巴以下的末端行。RGBA 缩图按预乘 alpha 平均，透明区的 RGB 不会染到人像。
    strip = result.crop((0, seam - rows, result.width, seam))
    body_color = np.asarray(strip.resize((result.width, 1), Image.Resampling.BOX))[0, :, :3].astype(
        np.float32
    )
    boundary = np.asarray(strip)[-1]
    fade_height = result.height - seam
    t = np.arange(1, fade_height + 1, dtype=np.float32) / max(2, fade_height)
    weight = 1 - t**2 * (3 - 2 * t)
    extension = np.empty((fade_height, result.width, 4), dtype=np.uint8)
    extension[:, :, :3] = np.rint(body_color + (boundary[:, :3] - body_color) * weight[:, None, None])
    extension[:, :, 3] = np.rint(boundary[:, 3] * weight[:, None])
    result.paste(Image.fromarray(extension), (0, seam))


def crop_portrait(
    image: Image.Image, size: tuple[int, int], face: Face | None
) -> tuple[Image.Image, Face | None]:
    """按输出比例取景，保留透明区并在需要时渐隐延伸人像下沿。"""
    width, height = size
    ratio = width / height
    alpha = image.getchannel("A") if face is not None and image.mode == "RGBA" else None
    if alpha is not None and alpha.getextrema()[0] > 127:
        alpha = None
    if face is None:
        crop_height = min(image.height, image.width / ratio)
        crop_width = crop_height * ratio
        left = (image.width - crop_width) / 2
        top = (image.height - crop_height) / 2
    else:
        # 输入和输出都用同一个缩放系数，确保五官比例不变。
        head_top = _head_top(face, alpha)
        head_height = max(face.y + face.height - head_top, face.height)
        # 保持双眼居中和头顶留白。缩小取景框能同时减少底部和两侧的溢出。
        bottom_limit = (image.height - head_top) / (1 - HEADROOM_RATIO)
        side_limit = 2 * min(face.center_x, image.width - face.center_x) / ratio
        crop_height = max(
            head_height / MAX_HEAD_HEIGHT_RATIO,
            min(head_height / HEAD_HEIGHT_RATIO, bottom_limit, side_limit),
        )
        crop_width = crop_height * ratio
        left = face.center_x - crop_width / 2
        top = head_top - HEADROOM_RATIO * crop_height

    box = (left, top, left + crop_width, top + crop_height)
    if left < 0 or top < 0 or box[2] > image.width or box[3] > image.height:
        image = image.convert("RGBA")
    result = image.transform(size, Image.Transform.EXTENT, box, Image.Resampling.BICUBIC)
    if face is None:
        return result, None
    scale = height / crop_height
    fitted = face.in_viewport(left, top, scale)
    if alpha is not None and box[3] > image.height:
        _fade_bottom(result, (image.height - top) * scale, fitted.y + fitted.height)
    return result, fitted
