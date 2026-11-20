"""规格底色的公共表示。"""

import re

from app.core.errors import AppError, ErrorCode

_COLORS = {
    "white": "#FFFFFF",
    "blue": "#438EDB",
    "red": "#FF0000",
    "dark_blue": "#1A3B8C",
    "grey": "#BFBFBF",
    "tint": "#EAF1FB",
    "gradient": "#438EDB",
    "sky_blue": "#87CEEB",  # 近似值
    "gray": "#BFBFBF",  # 近似值
    "dark_red": "#8B0000",  # 近似值
}
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")


def normalize_bg_color(value: str) -> str | None:
    """把已知底色名或六位色值转换为大写十六进制。"""
    value = value.strip()
    if _HEX_COLOR.fullmatch(value):
        return value.upper()
    return _COLORS.get(value.lower())


def require_bg_color(value: str) -> str:
    """校验导出所用的底色，并返回规范色值。"""
    color = normalize_bg_color(value)
    if color is None:
        raise AppError(ErrorCode.VALIDATION_ERROR, "底色必须是已知颜色名或六位十六进制色值")
    return color
