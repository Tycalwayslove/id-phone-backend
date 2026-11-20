"""省级、地级行政区划名称与代码。"""

import json
import re
from pathlib import Path

_DATA = json.loads((Path(__file__).parents[1] / "data" / "regions.json").read_text(encoding="utf-8"))
_NAMES: dict[str, str] = {}
_PROVINCES: dict[str, str] = {}
_ALIASES: dict[str, str] = {}
for _province in _DATA:
    for _region in [_province, *_province["cities"]]:
        _code = _region["code"]
        _NAMES[_code] = _region["name"]
        _PROVINCES[_code] = _province["code"]
        _ALIASES[_region["name"]] = _ALIASES[_region["short"]] = _code

# 全称先于同一位置上的简称，例如“吉林省”不会被识别为吉林市。
_PATTERN = re.compile("|".join(map(re.escape, sorted(_ALIASES, key=len, reverse=True))))


def resolve_region(name: str) -> str | None:
    """从名称中优先识别市，其次识别省；同一级别取最长的匹配。"""
    alias = max(
        _PATTERN.findall(name),
        key=lambda word: (_PROVINCES[_ALIASES[word]] != _ALIASES[word], len(word)),
        default=None,
    )
    return _ALIASES[alias] if alias is not None else None


def province_of(code: str) -> str | None:
    """返回所属省级代码；传入省级代码时返回自身。"""
    return _PROVINCES.get(code)


def region_name(code: str | None) -> str | None:
    """返回区划全称；全国通用或未知代码返回空。"""
    return _NAMES.get(code) if code else None
