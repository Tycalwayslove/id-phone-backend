"""图片处理（Pillow）：校验上传图片、按规格生成导出图。纯函数，不碰数据库和存储。"""

import io
from collections.abc import Sequence

from PIL import (
    Image,
    ImageColor,
    ImageDraw,
    ImageFont,
    ImageOps,
    UnidentifiedImageError,
)

from app.core.colors import require_bg_color
from app.modules.photos.pipeline.crop import crop_portrait
from app.modules.photos.pipeline.face import Face, Point
from app.modules.photos.pipeline.retouch import retouch

# 上传允许的格式：Pillow 识别出的格式 → (mime, 扩展名)
ALLOWED_FORMATS = {"JPEG": ("image/jpeg", "jpg"), "PNG": ("image/png", "png")}
MIN_SIDE_PX = 300
# 防止“解压炸弹”：像素总数上限
MAX_PIXELS = 50_000_000

JPEG_QUALITY_START = 95
JPEG_QUALITY_MIN = 60
JPEG_QUALITY_STEP = 5


class ImageInvalidError(ValueError):
    """上传的内容不是合格的图片。"""


def inspect_image(data: bytes) -> tuple[str, int, int]:
    """校验确实是 JPEG/PNG 图片且宽高都不小于 300，返回 (格式, 宽, 高)。"""
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt, (w, h) = img.format, img.size
            if fmt not in ALLOWED_FORMATS:
                raise ImageInvalidError("只支持 JPEG 或 PNG 图片")
            if w * h > MAX_PIXELS:
                raise ImageInvalidError("图片像素太大")
            img.load()  # 完整解码一遍，截断或损坏的图片会在这里报错
    except ImageInvalidError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as e:
        raise ImageInvalidError("文件不是有效的图片") from e
    if w < MIN_SIDE_PX or h < MIN_SIDE_PX:
        raise ImageInvalidError(f"图片宽高都不能小于 {MIN_SIDE_PX} 像素")
    return fmt, w, h


def decode_photo(data: bytes) -> Image.Image:
    """按 EXIF 纠正方向，并保留透明通道供抠图、裁剪和铺底色使用。"""
    with Image.open(io.BytesIO(data)) as src:
        ImageOps.exif_transpose(src, in_place=True)
        has_alpha = src.mode in ("RGBA", "LA") or "transparency" in src.info
        return src.convert("RGBA" if has_alpha else "RGB")


def _apply_watermark(img: Image.Image) -> Image.Image:
    """在图上平铺半透明文字 PREVIEW。"""
    w, h = img.size
    font = ImageFont.load_default(size=max(12, w // 8))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    left, top, right, bottom = draw.textbbox((0, 0), "PREVIEW", font=font)
    tw, th = right - left, bottom - top
    step_x, step_y = tw + tw // 2, th * 3
    for row, y in enumerate(range(0, h, step_y)):
        offset = -(step_x // 2) if row % 2 else 0
        for x in range(offset, w, step_x):
            draw.text((x - left, y - top), "PREVIEW", font=font, fill=(128, 128, 128, 110))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def make_render(
    data: bytes,
    *,
    width_px: int,
    height_px: int,
    bg_color: str,
    dpi: int,
    max_kb: int | None,
    watermarked: bool,
    beauty_level: int = 0,
    face: Face | None = None,
    blemishes: Sequence[Point] = (),
) -> bytes:
    """把底片（抠图或原图）导出成规格要求的 JPEG 字节。

    步骤：纠正方向、按人脸裁剪、校正光影并精修、铺底色、加预览水印、压缩。
    """
    bg_color = require_bg_color(bg_color)
    with decode_photo(data) as source:
        has_foreground_mask = source.mode == "RGBA"
        img, fitted_face = crop_portrait(source, (width_px, height_px), face)
    img = retouch(
        img,
        fitted_face,
        beauty_level=beauty_level,
        blemishes=blemishes,
        has_foreground_mask=has_foreground_mask,
    )
    if img.mode == "RGBA":
        canvas = Image.new("RGB", img.size, ImageColor.getrgb(bg_color))
        canvas.paste(img, mask=img.getchannel("A"))
        img = canvas
    if watermarked:
        img = _apply_watermark(img)

    quality = JPEG_QUALITY_START
    while True:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality, dpi=(dpi, dpi), optimize=True)
        out = buf.getvalue()
        if max_kb is None or len(out) <= max_kb * 1024 or quality <= JPEG_QUALITY_MIN:
            return out
        quality = max(JPEG_QUALITY_MIN, quality - JPEG_QUALITY_STEP)
