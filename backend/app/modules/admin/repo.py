"""后台查询、行锁和会话吊销。跨模块只读查询不按用户过滤，仅供 admin 使用。"""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, defer

from app.core.pagination import OffsetPageParams, paginate
from app.core.utils import contains_pattern, utcnow
from app.models import (
    AdminSession,
    AdminUser,
    AuditLog,
    Channel,
    ClientApp,
    NotifyTask,
    Order,
    OrderItem,
    Payment,
    Plan,
    PlanBenefit,
    Provider,
    ProviderSpec,
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


def list_admin_accounts(db: Session, *, page: OffsetPageParams) -> tuple[list[AdminUser], int]:
    stmt = select(AdminUser).options(defer(AdminUser.password_hash))
    rows, total = paginate(db, stmt.order_by(AdminUser.id.desc()), page)
    return [row for (row,) in rows], total


def lock_admin_for_login(db: Session, admin_id: int) -> AdminUser | None:
    return db.get(AdminUser, admin_id, populate_existing=True, with_for_update={"key_share": True})


def lock_admin_accounts(db: Session, admin_id: int, target_id: int) -> list[AdminUser]:
    # 涉及所有者的写操作按同一顺序锁行，并读取锁定后的最新角色和状态。
    stmt = (
        select(AdminUser)
        .where(
            or_(
                AdminUser.id.in_((admin_id, target_id)),
                (AdminUser.role == "owner") & (AdminUser.status == "active"),
            )
        )
        .order_by(AdminUser.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    return list(db.scalars(stmt))


def revoke_admin_sessions(db: Session, admin_id: int) -> None:
    db.execute(
        update(AdminSession)
        .where(AdminSession.admin_id == admin_id, AdminSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def get_session_by_hash(db: Session, token_hash: str) -> AdminSession | None:
    return db.scalar(select(AdminSession).where(AdminSession.token_hash == token_hash))


# ---------- 看板与通知 ----------


def overview_counts(db: Session) -> tuple[int, int, int, int]:
    paid = Order.status.in_(PAID_STATUSES)
    user_count, order_count, paid_count, paid_fen = db.execute(
        select(
            select(func.count(User.id)).scalar_subquery(),
            func.count(Order.id),
            func.count(Order.id).filter(paid),
            func.coalesce(func.sum(Order.paid_fen).filter(paid), 0),
        )
    ).one()
    return user_count, order_count, paid_count, paid_fen


def list_notify_tasks(
    db: Session, *, status: str | None, page: OffsetPageParams
) -> tuple[list[NotifyTask], int]:
    # notify 目前没有后台列表 service，使用后台只读查询例外。
    stmt = select(NotifyTask).options(defer(NotifyTask.result))
    if status is not None:
        stmt = stmt.where(NotifyTask.status == status)
    rows, total = paginate(db, stmt.order_by(NotifyTask.id.desc()), page)
    return [row for (row,) in rows], total


# ---------- 用户 ----------


def list_users(
    db: Session,
    *,
    user_id: int | None,
    phone_hash: str | None,
    status: str | None,
    source_app_id: int | None,
    page: OffsetPageParams,
) -> tuple[list[User], int]:
    stmt = select(User)
    if user_id is not None:
        stmt = stmt.where(User.id == user_id)
    if phone_hash is not None:
        stmt = stmt.where(User.phone_hash == phone_hash)
    if status is not None:
        stmt = stmt.where(User.status == status)
    if source_app_id is not None:
        stmt = stmt.where(User.source_app_id == source_app_id)
    rows, total = paginate(db, stmt.order_by(User.id.desc()), page)
    return [row for (row,) in rows], total


def get_user(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def user_sources(db: Session, user_ids: list[int]) -> dict[int, tuple[ClientApp | None, str | None]]:
    if not user_ids:
        return {}
    stmt = (
        select(User.id, ClientApp, Channel.name)
        .outerjoin(ClientApp, ClientApp.id == User.source_app_id)
        .outerjoin(Channel, Channel.id == User.first_channel_id)
        .where(User.id.in_(user_ids))
    )
    return {user_id: (app, channel_name) for user_id, app, channel_name in db.execute(stmt)}


def list_client_apps(db: Session, *, page: OffsetPageParams) -> tuple[list[ClientApp], int]:
    stmt = select(ClientApp)
    rows, total = paginate(db, stmt.order_by(ClientApp.id.desc()), page)
    return [row for (row,) in rows], total


def client_app_user_counts(db: Session, app_ids: list[int]) -> dict[int, int]:
    if not app_ids:
        return {}
    stmt = (
        select(User.source_app_id, func.count())
        .where(User.source_app_id.in_(app_ids))
        .group_by(User.source_app_id)
    )
    return {app_id: count for app_id, count in db.execute(stmt)}


def lock_client_app(db: Session, app_id: int) -> ClientApp | None:
    return db.get(ClientApp, app_id, populate_existing=True, with_for_update={"key_share": True})


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


# ---------- 订单 ----------


def list_orders(
    db: Session,
    *,
    status: str | None,
    order_no: str | None,
    user_id: int | None,
    created_from: datetime | None,
    created_to: datetime | None,
    page: OffsetPageParams,
) -> tuple[list[Order], int]:
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
    rows, total = paginate(db, stmt.order_by(Order.id.desc()), page)
    return [row for (row,) in rows], total


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


def specs_by_ids(db: Session, ids: Iterable[int]) -> dict[int, Spec]:
    ids = set(ids)
    if not ids:
        return {}
    return {s.id: s for s in db.scalars(select(Spec).where(Spec.id.in_(ids)))}


def list_specs(
    db: Session,
    *,
    keyword: str | None,
    status: str | None,
    category: str | None,
    region_code: str | None,
    page: OffsetPageParams,
) -> tuple[list[Spec], int]:
    stmt = select(Spec)
    if keyword:
        pattern = contains_pattern(keyword)
        stmt = stmt.where(or_(Spec.name.ilike(pattern, escape="\\"), Spec.code.ilike(pattern, escape="\\")))
    if status:
        stmt = stmt.where(Spec.status == status)
    if category:
        stmt = stmt.where(Spec.category == category)
    if region_code:
        stmt = stmt.where(Spec.region_code == region_code)
    rows, total = paginate(db, stmt.order_by(Spec.id.desc()), page)
    return [row for (row,) in rows], total


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


def provider_spec_counts(db: Session) -> dict[int, tuple[int, int]]:
    """每个服务商的 (规格映射总数, 已启用数)。"""
    stmt = select(
        ProviderSpec.provider_id,
        func.count(),
        func.count().filter(ProviderSpec.is_enabled),
    ).group_by(ProviderSpec.provider_id)
    return {pid: (total, enabled) for pid, total, enabled in db.execute(stmt).tuples()}


def route_rule_counts(db: Session) -> dict[int, int]:
    stmt = select(RouteRule.provider_id, func.count()).group_by(RouteRule.provider_id)
    return dict(db.execute(stmt).tuples().all())


def list_provider_specs(
    db: Session,
    *,
    provider_code: str | None,
    keyword: str | None,
    is_enabled: bool | None,
    page: OffsetPageParams,
) -> tuple[list[tuple[ProviderSpec, str, Spec]], int]:
    """服务商规格映射，按 id 倒序；返回 (映射, 服务商编码, 规格)。"""
    stmt = (
        select(ProviderSpec, Provider.code, Spec)
        .join(Provider, Provider.id == ProviderSpec.provider_id)
        .join(Spec, Spec.id == ProviderSpec.spec_id)
    )
    if provider_code:
        stmt = stmt.where(Provider.code == provider_code)
    if keyword:
        pattern = contains_pattern(keyword)
        stmt = stmt.where(
            or_(
                Spec.name.ilike(pattern, escape="\\"),
                Spec.code.ilike(pattern, escape="\\"),
                ProviderSpec.provider_item_id.ilike(pattern, escape="\\"),
            )
        )
    if is_enabled is not None:
        stmt = stmt.where(ProviderSpec.is_enabled.is_(is_enabled))
    return paginate(db, stmt.order_by(ProviderSpec.id.desc()), page)


def list_route_rules(
    db: Session,
    *,
    provider_code: str | None,
    spec_code: str | None,
    page: OffsetPageParams,
) -> tuple[list[tuple[RouteRule, str, Spec]], int]:
    """路由规则，按 id 倒序；返回 (规则, 服务商编码, 规格)。"""
    stmt = (
        select(RouteRule, Provider.code, Spec)
        .join(Provider, Provider.id == RouteRule.provider_id)
        .join(Spec, Spec.id == RouteRule.spec_id)
    )
    if provider_code:
        stmt = stmt.where(Provider.code == provider_code)
    if spec_code:
        stmt = stmt.where(Spec.code == spec_code)
    return paginate(db, stmt.order_by(RouteRule.id.desc()), page)


def lock_provider_spec(db: Session, entry_id: int) -> ProviderSpec | None:
    return db.get(ProviderSpec, entry_id, populate_existing=True, with_for_update=True)


def lock_route_rule(db: Session, rule_id: int) -> RouteRule | None:
    return db.get(RouteRule, rule_id, populate_existing=True, with_for_update=True)


def routing_references(db: Session, entry: ProviderSpec | RouteRule) -> tuple[str, Spec]:
    model = type(entry)
    provider_code, spec = db.execute(
        select(Provider.code, Spec)
        .select_from(model)
        .join(Provider, Provider.id == model.provider_id)
        .join(Spec, Spec.id == model.spec_id)
        .where(model.id == entry.id)
    ).one()
    return provider_code, spec


# ---------- 审计 ----------


def list_audit_logs(
    db: Session,
    *,
    admin_id: int | None,
    action: str | None,
    target_type: str | None,
    page: OffsetPageParams,
) -> tuple[list[tuple[AuditLog, str | None]], int]:
    stmt = select(AuditLog, AdminUser.username).outerjoin(AdminUser, AdminUser.id == AuditLog.admin_id)
    if admin_id is not None:
        stmt = stmt.where(AuditLog.admin_id == admin_id)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if target_type is not None:
        stmt = stmt.where(AuditLog.target_type == target_type)
    return paginate(db, stmt.order_by(AuditLog.id.desc()), page)
