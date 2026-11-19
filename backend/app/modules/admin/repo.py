"""后台查询。后台是“只读直查各业务表”的例外：函数不按用户过滤，只给 admin 模块自己用。"""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AdminSession,
    AdminUser,
    AuditLog,
    Order,
    OrderItem,
    Payment,
    Plan,
    PlanBenefit,
    Provider,
    ProviderSpec,
    ReceiptApplication,
    ReceiptAttempt,
    Refund,
    RouteRule,
    Spec,
    User,
    UserIdentity,
)

PAID_STATUSES = ("paid", "part_refunded", "refunded")

# ---------- 账号与会话 ----------


def get_admin_by_username(db: Session, username: str) -> AdminUser | None:
    return db.scalar(select(AdminUser).where(AdminUser.username == username))


def get_session_by_hash(db: Session, token_hash: str) -> AdminSession | None:
    return db.scalar(select(AdminSession).where(AdminSession.token_hash == token_hash))


# ---------- 用户 ----------


def list_users(
    db: Session,
    *,
    user_id: int | None,
    phone_hash: str | None,
    status: str | None,
    before_id: int | None,
    limit: int,
) -> list[User]:
    stmt = select(User)
    if user_id is not None:
        stmt = stmt.where(User.id == user_id)
    if phone_hash is not None:
        stmt = stmt.where(User.phone_hash == phone_hash)
    if status is not None:
        stmt = stmt.where(User.status == status)
    if before_id is not None:
        stmt = stmt.where(User.id < before_id)
    return list(db.scalars(stmt.order_by(User.id.desc()).limit(limit)))


def get_user(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def user_order_stats(db: Session, user_ids: Iterable[int]) -> dict[int, tuple[int, int]]:
    ids = list(user_ids)
    if not ids:
        return {}
    rows = db.execute(
        select(Order.user_id, func.count(Order.id), func.coalesce(func.sum(Order.paid_fen), 0))
        .where(Order.user_id.in_(ids), Order.status.in_(PAID_STATUSES))
        .group_by(Order.user_id)
    )
    return {uid: (int(c), int(s)) for uid, c, s in rows}


def identity_providers(db: Session, user_ids: Iterable[int]) -> dict[int, list[str]]:
    ids = list(user_ids)
    result: dict[int, list[str]] = {i: [] for i in ids}
    if not ids:
        return result
    rows = db.execute(
        select(UserIdentity.user_id, UserIdentity.provider)
        .where(UserIdentity.user_id.in_(ids))
        .distinct()
        .order_by(UserIdentity.user_id, UserIdentity.provider)
    )
    for uid, provider in rows:
        result[uid].append(provider)
    return result


def applications_count(db: Session, user_id: int) -> int:
    return int(
        db.scalar(select(func.count(ReceiptApplication.id)).where(ReceiptApplication.user_id == user_id)) or 0
    )


# ---------- 订单 ----------


def list_orders(
    db: Session,
    *,
    status: str | None,
    order_no: str | None,
    user_id: int | None,
    created_from: datetime | None,
    created_to: datetime | None,
    before_id: int | None,
    limit: int,
) -> list[Order]:
    stmt = select(Order)
    if status is not None:
        stmt = stmt.where(Order.status == status)
    if order_no is not None:
        stmt = stmt.where(Order.order_no == order_no)
    if user_id is not None:
        stmt = stmt.where(Order.user_id == user_id)
    if created_from is not None:
        stmt = stmt.where(Order.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(Order.created_at < created_to)
    if before_id is not None:
        stmt = stmt.where(Order.id < before_id)
    return list(db.scalars(stmt.order_by(Order.id.desc()).limit(limit)))


def get_order_by_no(db: Session, order_no: str) -> Order | None:
    return db.scalar(select(Order).where(Order.order_no == order_no))


def items_by_order(db: Session, order_ids: list[int]) -> dict[int, list[OrderItem]]:
    result: dict[int, list[OrderItem]] = {i: [] for i in order_ids}
    if order_ids:
        for it in db.scalars(
            select(OrderItem).where(OrderItem.order_id.in_(order_ids)).order_by(OrderItem.id)
        ):
            result[it.order_id].append(it)
    return result


def payments_of(db: Session, order_id: int) -> list[Payment]:
    return list(db.scalars(select(Payment).where(Payment.order_id == order_id).order_by(Payment.id)))


def refunds_of(db: Session, order_id: int) -> list[Refund]:
    return list(db.scalars(select(Refund).where(Refund.order_id == order_id).order_by(Refund.id)))


# ---------- 回执申请 ----------


def list_applications(
    db: Session,
    *,
    status: str | None,
    app_no: str | None,
    user_id: int | None,
    spec_code: str | None,
    before_id: int | None,
    limit: int,
) -> list[ReceiptApplication]:
    stmt = select(ReceiptApplication)
    if spec_code is not None:
        stmt = stmt.join(Spec, Spec.id == ReceiptApplication.spec_id).where(Spec.code == spec_code)
    if status is not None:
        stmt = stmt.where(ReceiptApplication.status == status)
    if app_no is not None:
        stmt = stmt.where(ReceiptApplication.app_no == app_no)
    if user_id is not None:
        stmt = stmt.where(ReceiptApplication.user_id == user_id)
    if before_id is not None:
        stmt = stmt.where(ReceiptApplication.id < before_id)
    return list(db.scalars(stmt.order_by(ReceiptApplication.id.desc()).limit(limit)))


def get_application_by_no(db: Session, app_no: str) -> ReceiptApplication | None:
    return db.scalar(select(ReceiptApplication).where(ReceiptApplication.app_no == app_no))


def specs_by_ids(db: Session, ids: Iterable[int]) -> dict[int, Spec]:
    ids = set(ids)
    if not ids:
        return {}
    return {s.id: s for s in db.scalars(select(Spec).where(Spec.id.in_(ids)))}


def attempts_by_app(db: Session, app_ids: list[int]) -> dict[int, list[tuple[ReceiptAttempt, str]]]:
    result: dict[int, list[tuple[ReceiptAttempt, str]]] = {i: [] for i in app_ids}
    if not app_ids:
        return result
    rows = db.execute(
        select(ReceiptAttempt, Provider.code)
        .join(Provider, Provider.id == ReceiptAttempt.provider_id)
        .where(ReceiptAttempt.application_id.in_(app_ids))
        .order_by(ReceiptAttempt.application_id, ReceiptAttempt.seq)
    )
    for attempt, code in rows:
        result[attempt.application_id].append((attempt, code))
    return result


# ---------- 套餐 ----------


def list_plans(db: Session) -> list[Plan]:
    return list(db.scalars(select(Plan).order_by(Plan.sort, Plan.id)))


def get_plan_by_code(db: Session, code: str, *, for_update: bool = False) -> Plan | None:
    stmt = select(Plan).where(Plan.code == code)
    if for_update:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def benefit_rows(db: Session, plan_ids: list[int]) -> dict[int, list[PlanBenefit]]:
    result: dict[int, list[PlanBenefit]] = {i: [] for i in plan_ids}
    if plan_ids:
        for b in db.scalars(select(PlanBenefit).where(PlanBenefit.plan_id.in_(plan_ids))):
            result[b.plan_id].append(b)
    return result


# ---------- 规格 ----------


def list_specs(db: Session, *, before_id: int | None, limit: int) -> list[Spec]:
    stmt = select(Spec)
    if before_id is not None:
        stmt = stmt.where(Spec.id < before_id)
    return list(db.scalars(stmt.order_by(Spec.id.desc()).limit(limit)))


def get_spec_by_code(db: Session, code: str, *, for_update: bool = False) -> Spec | None:
    stmt = select(Spec).where(Spec.code == code)
    if for_update:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def spec_codes(db: Session, ids: Iterable[int]) -> dict[int, str]:
    ids = set(ids)
    if not ids:
        return {}
    return dict(db.execute(select(Spec.id, Spec.code).where(Spec.id.in_(ids))).tuples().all())


# ---------- 服务商 ----------


def list_providers(db: Session) -> list[Provider]:
    return list(db.scalars(select(Provider).order_by(Provider.id)))


def get_provider_by_code(db: Session, code: str, *, for_update: bool = False) -> Provider | None:
    stmt = select(Provider).where(Provider.code == code)
    if for_update:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def provider_specs(db: Session) -> list[ProviderSpec]:
    return list(db.scalars(select(ProviderSpec).order_by(ProviderSpec.id)))


def route_rules(db: Session) -> list[RouteRule]:
    return list(db.scalars(select(RouteRule).order_by(RouteRule.priority, RouteRule.id)))


# ---------- 审计 ----------


def list_audit_logs(
    db: Session,
    *,
    admin_id: int | None,
    action: str | None,
    target_type: str | None,
    before_id: int | None,
    limit: int,
) -> list[tuple[AuditLog, str | None]]:
    stmt = select(AuditLog, AdminUser.username).outerjoin(AdminUser, AdminUser.id == AuditLog.admin_id)
    if admin_id is not None:
        stmt = stmt.where(AuditLog.admin_id == admin_id)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if target_type is not None:
        stmt = stmt.where(AuditLog.target_type == target_type)
    if before_id is not None:
        stmt = stmt.where(AuditLog.id < before_id)
    return [(a, u) for a, u in db.execute(stmt.order_by(AuditLog.id.desc()).limit(limit))]
