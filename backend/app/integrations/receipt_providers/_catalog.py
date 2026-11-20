"""鹧应和黔微云目录的字段规范化。"""

import json
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# 保留旧数据修复脚本使用的导入路径。
from app.core.colors import _COLORS as _COLORS
from app.core.colors import normalize_bg_color
from app.core.errors import AppError, ErrorCode
from app.integrations.receipt_providers.base import ProviderItem

_CATALOG_FIELDS = (
    "item_id",
    "id",
    "name",
    "color",
    "width_px",
    "height_px",
    "width_mm",
    "height_mm",
    "dpi",
    "file_size_msg",
    "file_size_min",
    "file_size_max",
    "sort",
    "category",
    "category_id",
    "is_receipt",
    "receipt_param",
)
_MAX_INTEGER = 2**31 - 1


def _colors(value: object) -> tuple[list[str], int]:
    if isinstance(value, str):
        value = json.loads(value.replace("'", '"'))
    if not isinstance(value, list) or any(not isinstance(name, str) for name in value):
        raise ValueError
    colors = []
    unknown = 0
    for name in value:
        name = name.strip().lower()
        if name.startswith("pose_"):
            continue
        color = normalize_bg_color(name)
        if color is None:
            unknown += 1
        elif color not in colors:
            colors.append(color)
    return colors, unknown


def _receipt_fields(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError, RecursionError:
            return []
    if not isinstance(value, list) or any(
        not isinstance(field, str) or not field.strip() or "\x00" in field for field in value
    ):
        return []
    return list(dict.fromkeys(value))


def _integer(value: object, *, minimum: int = 0) -> int:
    if type(value) not in (int, str):
        raise ValueError
    number = int(value)
    if not minimum <= number <= _MAX_INTEGER:
        raise ValueError
    return number


def _millimeters(value: object) -> int | None:
    if value in (None, ""):
        return None
    number = Decimal(str(value))
    if not 0 <= number <= _MAX_INTEGER:
        raise ValueError
    # 规格表的毫米字段是整数。原始精度保留在 raw。
    return int(number.to_integral_value(rounding=ROUND_HALF_UP)) or None


def parse_item(data: object, *, id_field: str) -> ProviderItem:
    if isinstance(data, dict):
        try:
            item_id, name = data[id_field], data["name"]
            if type(item_id) is int and item_id > 0:
                item_id = str(item_id)
            if (
                not isinstance(item_id, str)
                or not item_id.strip()
                or len(item_id) > 128
                or not isinstance(name, str)
                or not name.strip()
                or "\x00" in item_id
                or "\x00" in name
            ):
                raise ValueError
            # 文档未标注 file_size_min/max 单位，按 KB 存。0 上限视为无限制。
            min_value, max_value = data.get("file_size_min"), data.get("file_size_max")
            size_min = None if min_value in (None, "") else _integer(min_value)
            size_max = None if max_value in (None, "") else _integer(max_value) or None
            if size_min is not None and size_max is not None and size_min > size_max:
                raise ValueError
            colors, unknown_color_count = _colors(data["color"])
            is_receipt = data.get("is_receipt")
            category = data.get("category")
            return ProviderItem(
                provider_item_id=item_id.strip(),
                name=name.strip(),
                bg_colors=colors,
                width_px=_integer(data["width_px"], minimum=1),
                height_px=_integer(data["height_px"], minimum=1),
                width_mm=_millimeters(data.get("width_mm")),
                height_mm=_millimeters(data.get("height_mm")),
                dpi=_integer(data["dpi"], minimum=1),
                file_size_min_kb=size_min,
                file_size_max_kb=size_max,
                sort=_integer(data.get("sort") or 0, minimum=-(2**31)),
                raw={key: data[key] for key in _CATALOG_FIELDS if key in data},
                is_receipt=(
                    True if is_receipt in (True, "1") else False if is_receipt in (False, "0") else None
                ),
                receipt_fields=_receipt_fields(data.get("receipt_param")),
                provider_category=str(category) if type(category) in (str, int) else None,
                unknown_color_count=unknown_color_count,
            )
        except KeyError, ValueError, InvalidOperation, RecursionError:
            pass
    raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "回执服务商规格数据无效")
