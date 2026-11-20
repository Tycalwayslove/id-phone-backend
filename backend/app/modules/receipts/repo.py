"""回执查询。C 端查询函数第一个参数是 user_id，查不到返回 None。"""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.models import (
    Entitlement,
    File,
    Provider,
    ProviderCallback,
    ProviderSpec,
    ReceiptApplication,
    ReceiptAttempt,
    RouteRule,
    Spec,
)

POLLABLE_STATUSES = ("submitted", "unknown", "processing")
REFUND_CANCELLABLE_STATUSES = ("pending", "processing", "rejected")


# ---------- C 端（带用户） ----------


def get_application(
    db: Session, user_id: int, app_no: str, *, for_update: bool = False
) -> ReceiptApplication | None:
    stmt = select(ReceiptApplication).where(
        ReceiptApplication.user_id == user_id, ReceiptApplication.app_no == app_no
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return db.scalar(stmt)


def lock_refundable_applications(db: Session, entitlement_ids: set[int]) -> list[ReceiptApplication]:
    stmt = (
        select(ReceiptApplication)
        .where(
            ReceiptApplication.entitlement_id.in_(entitlement_ids),
            ReceiptApplication.status.in_(REFUND_CANCELLABLE_STATUSES),
        )
        .order_by(ReceiptApplication.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list(db.scalars(stmt))


def list_applications(
    db: Session, user_id: int, *, before_id: int | None, limit: int
) -> list[ReceiptApplication]:
    stmt = select(ReceiptApplication).where(ReceiptApplication.user_id == user_id)
    if before_id is not None:
        stmt = stmt.where(ReceiptApplication.id < before_id)
    return list(db.scalars(stmt.order_by(ReceiptApplication.id.desc()).limit(limit)))


# ---------- 内部（回调、轮询、联调用，不带用户） ----------


def get_application_by_id(db: Session, app_id: int, *, for_update: bool = False) -> ReceiptApplication | None:
    stmt = select(ReceiptApplication).where(ReceiptApplication.id == app_id)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return db.scalar(stmt)


def find_route(db: Session, spec_id: int, region_code: str | None) -> tuple[Provider, ProviderSpec] | None:
    """按路由规则选服务商：优先级数字小的优先；同优先级时指定了地区的规则排在“不限地区”前面。"""
    region_cond = RouteRule.region_code.is_(None)
    if region_code:
        region_cond = or_(region_cond, RouteRule.region_code == region_code)
    row = db.execute(
        select(Provider, ProviderSpec)
        .select_from(RouteRule)
        .join(Provider, Provider.id == RouteRule.provider_id)
        .join(
            ProviderSpec,
            and_(
                ProviderSpec.provider_id == RouteRule.provider_id, ProviderSpec.spec_id == RouteRule.spec_id
            ),
        )
        .where(
            RouteRule.spec_id == spec_id,
            RouteRule.is_enabled.is_(True),
            region_cond,
            Provider.status == "enabled",
            ProviderSpec.is_enabled.is_(True),
        )
        .order_by(RouteRule.priority, RouteRule.region_code.is_(None), RouteRule.id)
        .limit(1)
    ).first()
    return (row[0], row[1]) if row else None


def get_provider_by_code(db: Session, code: str) -> Provider | None:
    return db.scalar(select(Provider).where(Provider.code == code))


def get_current_attempt(db: Session, application_id: int) -> ReceiptAttempt | None:
    return db.scalar(
        select(ReceiptAttempt).where(
            ReceiptAttempt.application_id == application_id, ReceiptAttempt.is_current.is_(True)
        )
    )


def last_seq(db: Session, application_id: int) -> int:
    return (
        db.scalar(select(func.max(ReceiptAttempt.seq)).where(ReceiptAttempt.application_id == application_id))
        or 0
    )


def demote_current(db: Session, application_id: int) -> None:
    """把该申请原来的当前提交置为非当前（部分唯一索引要求先做这一步）。"""
    db.execute(
        update(ReceiptAttempt)
        .where(ReceiptAttempt.application_id == application_id, ReceiptAttempt.is_current.is_(True))
        .values(is_current=False)
        .execution_options(synchronize_session="fetch")
    )
    db.flush()


def get_attempt_by_order(db: Session, provider_id: int, provider_order_no: str) -> ReceiptAttempt | None:
    return db.scalar(
        select(ReceiptAttempt).where(
            ReceiptAttempt.provider_id == provider_id,
            ReceiptAttempt.provider_order_no == provider_order_no,
        )
    )


def get_callback_by_dedupe(db: Session, dedupe_key: str) -> ProviderCallback | None:
    return db.scalar(select(ProviderCallback).where(ProviderCallback.dedupe_key == dedupe_key))


def due_attempt_ids(db: Session, now: datetime, limit: int) -> list[int]:
    return list(
        db.scalars(
            select(ReceiptAttempt.id)
            .join(ReceiptApplication, ReceiptApplication.id == ReceiptAttempt.application_id)
            .where(
                ReceiptAttempt.is_current.is_(True),
                ReceiptAttempt.status.in_(POLLABLE_STATUSES),
                ReceiptAttempt.next_poll_at <= now,
                ReceiptApplication.status.in_(("pending", "processing")),
            )
            .order_by(ReceiptAttempt.next_poll_at)
            .limit(limit)
        )
    )


def get_attempt(db: Session, attempt_id: int, *, for_update: bool = False) -> ReceiptAttempt | None:
    stmt = select(ReceiptAttempt).where(ReceiptAttempt.id == attempt_id)
    if for_update:
        stmt = stmt.with_for_update(skip_locked=True)
    return db.scalar(stmt)


# ---------- 批量取关联数据（拼装返回用，避免逐条查询） ----------


def specs_by_ids(db: Session, ids: Iterable[int]) -> dict[int, Spec]:
    ids = set(ids)
    if not ids:
        return {}
    return {s.id: s for s in db.scalars(select(Spec).where(Spec.id.in_(ids)))}


def entitlements_by_ids(db: Session, ids: Iterable[int]) -> dict[int, Entitlement]:
    ids = set(ids)
    if not ids:
        return {}
    return {e.id: e for e in db.scalars(select(Entitlement).where(Entitlement.id.in_(ids)))}


def files_by_ids(db: Session, ids: Iterable[int]) -> dict[int, File]:
    ids = set(ids)
    if not ids:
        return {}
    return {f.id: f for f in db.scalars(select(File).where(File.id.in_(ids)))}


def attempts_by_app_ids(db: Session, app_ids: Iterable[int]) -> dict[int, list[ReceiptAttempt]]:
    app_ids = set(app_ids)
    out: dict[int, list[ReceiptAttempt]] = {}
    if not app_ids:
        return out
    rows = db.scalars(
        select(ReceiptAttempt)
        .where(ReceiptAttempt.application_id.in_(app_ids))
        .order_by(ReceiptAttempt.application_id, ReceiptAttempt.seq)
    )
    for a in rows:
        out.setdefault(a.application_id, []).append(a)
    return out
