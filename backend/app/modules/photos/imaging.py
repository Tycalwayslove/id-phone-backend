"""图片处理（Pillow）：校验上传图片、按规格生成导出图。纯函数，不碰数据库和存储。"""

import io

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

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


def _center_crop(img: Image.Image, ratio: float) -> Image.Image:
    """按宽高比 ratio（宽/高）居中裁剪。"""
    w, h = img.size
    if w / h > ratio:
        new_w = max(1, round(h * ratio))
        left = (w - new_w) // 2
        return img.crop((left, 0, left + new_w, h))
    new_h = max(1, round(w / ratio))
    top = (h - new_h) // 2
    return img.crop((0, top, w, top + new_h))


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
) -> bytes:
    """把底片（抠图或原图）导出成规格要求的 JPEG 字节。

    步骤：纠正方向 → 按宽高比居中裁剪 → 缩放 → 透明区域铺底色 → （预览）加水印 → 压缩到大小上限内。
    """
    # TODO: beauty_level 美颜暂未实现，先忽略
    with Image.open(io.BytesIO(data)) as src:
        img = ImageOps.exif_transpose(src)
        has_alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info
        img = img.convert("RGBA" if has_alpha else "RGB")
    img = _center_crop(img, width_px / height_px)
    img = img.resize((width_px, height_px), Image.Resampling.LANCZOS)
    if has_alpha:
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
