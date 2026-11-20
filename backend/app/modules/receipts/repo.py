"""回执查询。C 端查询函数第一个参数是 user_id，查不到返回 None。"""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.pagination import OffsetPageParams, paginate
from app.models import (
    Entitlement,
    File,
    IdempotencyKey,
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
CALLBACK_NONCE_HASH = "callback_nonce_sha256"
MANUAL_REVIEW_REQUIRED = "manual_review_required"
RECEIPT_IMAGE_URL = "receipt_image_url_enc"


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


def _admin_applications_query(
    *,
    status: str | None = None,
    app_no: str | None = None,
    user_id: int | None = None,
    spec_code: str | None = None,
    manual_review: bool | None = None,
):
    flagged_attempt = (
        select(ReceiptAttempt.id)
        .where(
            ReceiptAttempt.application_id == ReceiptApplication.id,
            ReceiptAttempt.is_current.is_(True),
            ReceiptAttempt.status.in_(POLLABLE_STATUSES),
            ReceiptAttempt.request_payload.contains({MANUAL_REVIEW_REQUIRED: True}),
        )
        .exists()
    )
    needs_review = and_(ReceiptApplication.status.in_(("pending", "processing")), flagged_attempt)
    stmt = select(ReceiptApplication, Spec, needs_review).join(Spec, Spec.id == ReceiptApplication.spec_id)
    if status is not None:
        stmt = stmt.where(ReceiptApplication.status == status)
    if app_no is not None:
        stmt = stmt.where(ReceiptApplication.app_no == app_no)
    if user_id is not None:
        stmt = stmt.where(ReceiptApplication.user_id == user_id)
    if spec_code is not None:
        stmt = stmt.where(Spec.code == spec_code)
    if manual_review is not None:
        stmt = stmt.where(needs_review.is_(manual_review))
    return stmt


def list_admin_applications(
    db: Session,
    *,
    page: OffsetPageParams,
    status: str | None = None,
    app_no: str | None = None,
    user_id: int | None = None,
    spec_code: str | None = None,
    manual_review: bool | None = None,
) -> tuple[list[tuple[ReceiptApplication, Spec, bool]], int]:
    stmt = _admin_applications_query(
        status=status, app_no=app_no, user_id=user_id, spec_code=spec_code, manual_review=manual_review
    ).order_by(ReceiptApplication.id.desc())
    return paginate(db, stmt, page)


def get_admin_application_summary(db: Session, app_no: str) -> tuple[ReceiptApplication, Spec, bool] | None:
    row = db.execute(_admin_applications_query(app_no=app_no)).one_or_none()
    if row is None:
        return None
    application, spec, needs_review = row
    return application, spec, needs_review


def get_admin_application_by_no(
    db: Session, app_no: str, *, for_update: bool = False
) -> ReceiptApplication | None:
    stmt = select(ReceiptApplication).where(ReceiptApplication.app_no == app_no)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return db.scalar(stmt)


def admin_attempts(db: Session, application_id: int) -> list[tuple[ReceiptAttempt, str]]:
    stmt = (
        select(ReceiptAttempt, Provider.code)
        .join(Provider, Provider.id == ReceiptAttempt.provider_id)
        .where(ReceiptAttempt.application_id == application_id)
        .order_by(ReceiptAttempt.seq)
    )
    return list(db.execute(stmt).tuples())


def application_counts_by_status(db: Session) -> dict[str, int]:
    stmt = select(ReceiptApplication.status, func.count(ReceiptApplication.id)).group_by(
        ReceiptApplication.status
    )
    return dict(db.execute(stmt).tuples().all())


def count_user_applications(db: Session, user_id: int) -> int:
    stmt = select(func.count(ReceiptApplication.id)).where(ReceiptApplication.user_id == user_id)
    return db.scalar(stmt) or 0


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


def find_attempt_by_nonce(db: Session, provider_id: int, digest: str) -> int | None:
    return db.scalar(
        select(ReceiptAttempt.id).where(
            ReceiptAttempt.provider_id == provider_id,
            ReceiptAttempt.request_payload[CALLBACK_NONCE_HASH].astext == digest,
        )
    )


def bind_provider_order(db: Session, attempt: ReceiptAttempt, order_no: str) -> bool:
    """用已有唯一约束处理同一服务商单号的并发绑定。"""
    try:
        with db.begin_nested():
            attempt.provider_order_no = order_no
            db.flush()
    except IntegrityError as exc:
        if (
            getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            != "uq_receipt_attempts_provider_order"
        ):
            raise
        return False
    return True


def save_submit_response(db: Session, user_id: int, scope: str, key: str, response: dict) -> None:
    db.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.user_id == user_id, IdempotencyKey.scope == scope, IdempotencyKey.key == key)
        .values(response_body=response)
    )


def get_callback_by_dedupe(db: Session, dedupe_key: str) -> ProviderCallback | None:
    return db.scalar(select(ProviderCallback).where(ProviderCallback.dedupe_key == dedupe_key))


def get_receipt_image_event(db: Session, attempt: ReceiptAttempt) -> ProviderCallback | None:
    return db.scalar(
        select(ProviderCallback).where(
            ProviderCallback.attempt_id == attempt.id,
            ProviderCallback.event_status == "3",
            ProviderCallback.process_result == "applied",
        )
    )


def due_attempt_ids(db: Session, now: datetime, limit: int) -> list[int]:
    return list(
        db.scalars(
            select(ReceiptAttempt.id)
            .join(ReceiptApplication, ReceiptApplication.id == ReceiptAttempt.application_id)
            .where(
                ReceiptAttempt.is_current.is_(True),
                ReceiptAttempt.next_poll_at <= now,
                or_(
                    and_(
                        ReceiptAttempt.status.in_(POLLABLE_STATUSES),
                        ReceiptApplication.status.in_(("pending", "processing")),
                    ),
                    and_(
                        ReceiptAttempt.status == "completed",
                        ReceiptApplication.status == "completed",
                        ReceiptApplication.receipt_file_id.is_(None),
                    ),
                ),
            )
            .order_by(ReceiptAttempt.next_poll_at)
            .limit(limit)
        )
    )


def lock_attempt(
    db: Session, attempt_id: int, *, skip_locked: bool = False
) -> tuple[ReceiptApplication, ReceiptAttempt] | None:
    """先锁申请，再读提交，以便与重提、退款、回调和轮询串行。"""
    app = db.scalar(
        select(ReceiptApplication)
        .join(ReceiptAttempt, ReceiptAttempt.application_id == ReceiptApplication.id)
        .where(ReceiptAttempt.id == attempt_id)
        .with_for_update(of=ReceiptApplication, skip_locked=skip_locked)
        .execution_options(populate_existing=True)
    )
    if app is None:
        return None
    attempt = db.get(ReceiptAttempt, attempt_id, populate_existing=True)
    return (app, attempt) if attempt is not None else None


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
