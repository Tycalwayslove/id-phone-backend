"""Idempotency-Key 支持：同一用户、同一操作、同一个 key 只真正执行一次。

用法（在 service 里）：

    def create_order(db, user_id, idem_key, payload) -> OrderOut:
        return run_idempotent(
            db, user_id=user_id, scope="orders.create", key=idem_key,
            request=payload.model_dump(mode="json"),
            produce=lambda: _do_create_order(db, user_id, payload),
            out_model=OrderOut,
        )

- key 为空：不做幂等，直接执行。
- 同一个 key、请求内容相同：直接返回第一次的结果，不重复执行。
- 同一个 key、请求内容不同：返回 IDEMPOTENCY_CONFLICT。
"""

import hashlib
import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models import IdempotencyKey


def _hash(request: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()


def run_idempotent[T: BaseModel](
    db: Session,
    *,
    user_id: int,
    scope: str,
    key: str | None,
    request: dict[str, Any],
    produce: Callable[[], T],
    out_model: type[T],
) -> T:
    if not key:
        result = produce()
        db.commit()
        return result

    req_hash = _hash(request)
    existing = db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id, IdempotencyKey.scope == scope, IdempotencyKey.key == key
        )
    )
    if existing is not None:
        if existing.request_hash != req_hash or existing.response_body is None:
            raise AppError(ErrorCode.IDEMPOTENCY_CONFLICT)
        return out_model.model_validate(existing.response_body)

    record = IdempotencyKey(user_id=user_id, scope=scope, key=key, request_hash=req_hash)
    db.add(record)
    try:
        db.flush()
    except IntegrityError as e:
        # 并发的同 key 请求：另一个已经占住了
        db.rollback()
        raise AppError(ErrorCode.IDEMPOTENCY_CONFLICT) from e

    result = produce()
    record.response_status = 200
    record.response_body = result.model_dump(mode="json")
    db.commit()
    return result
