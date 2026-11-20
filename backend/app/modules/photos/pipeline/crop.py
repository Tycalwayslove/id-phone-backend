"""计算证件照取景框和裁剪后的关键点位置。"""

from math import ceil

import numpy as np
from PIL import Image

from app.modules.photos.pipeline.face import Face

# T024 通用证件照构图。头高占成品 55%～70%，以 62% 为目标。
HEAD_HEIGHT_RATIO = 0.62
MAX_HEAD_HEIGHT_RATIO = 0.70
HEADROOM_RATIO = 0.08
BOTTOM_FADE_RATIO = 0.04


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
    start = max(0, ceil(chin - 0.5), seam - round(result.height * BOTTOM_FADE_RATIO))
    if start >= seam or seam >= result.height:
        return

    # 保留原图逐行纹理，线性衰减下巴以下的 alpha。越界区透明，导出时直接铺底色。
    alpha = result.getchannel("A")
    strip = np.asarray(alpha.crop((0, start, result.width, seam)))
    weight = np.arange(seam - start - 1, -1, -1, dtype=np.float32) / (seam - start)
    alpha.paste(Image.fromarray(np.rint(strip * weight[:, None]).astype(np.uint8)), (0, start))
    result.putalpha(alpha)


def crop_portrait(
    image: Image.Image, size: tuple[int, int], face: Face | None
) -> tuple[Image.Image, Face | None]:
    """按输出比例取景，底部越界时把原图下沿渐隐到底色。"""
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
    if box[3] > image.height:
        _fade_bottom(result, (image.height - top) * scale, fitted.y + fitted.height)
    return result, fitted
