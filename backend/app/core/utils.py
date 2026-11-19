"""时间、单号、游标分页等小工具。"""

import base64
import json
import secrets
from datetime import UTC, datetime
from typing import Any


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_no(prefix: str) -> str:
    """对外单号：前缀 + 时间 + 随机数，如 O20261119083012A1B2C3。不暴露自增 ID，也不连续。"""
    return f"{prefix}{utcnow():%Y%m%d%H%M%S}{secrets.token_hex(3).upper()}"


def encode_cursor(values: dict[str, Any]) -> str:
    raw = json.dumps(values, default=str, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
        return data if isinstance(data, dict) else None
    except ValueError:
        return None
