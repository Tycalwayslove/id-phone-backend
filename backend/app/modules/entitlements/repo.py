"""权益查询。C 端查询函数第一个参数是 user_id，查不到返回 None。

带 ent_id / quota_id 的内部函数不按用户过滤，调用方必须先用 user_id 查出权益。
"""

from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.models import Entitlement, EntitlementLedger, EntitlementQuota, Photo, Plan

RECEIPT_QUOTA = "receipt_quota"


def list_for_user(db: Session, user_id: int, *, status: str, now: datetime, limit: int) -> list[Entitlement]:
    stmt = select(Entitlement).where(Entitlement.user_id == user_id)
    if status == "active":
        stmt = stmt.where(Entitlement.status == "active", Entitlement.ends_at > now)
    elif status == "expired":
        stmt = stmt.where(or_(Entitlement.status != "active", Entitlement.ends_at <= now))
    stmt = stmt.order_by(Entitlement.ends_at.desc(), Entitlement.id.desc()).limit(limit)
    return list(db.scalars(stmt))


def get_for_user(db: Session, user_id: int, entitlement_id: int) -> Entitlement | None:
    return db.scalar(
        select(Entitlement).where(Entitlement.id == entitlement_id, Entitlement.user_id == user_id)
    )


def active_covering_photo(db: Session, user_id: int, photo_id: int, now: datetime) -> list[Entitlement]:
    """有效且覆盖这张照片的权益（photo_id 相同，或 photo_id 为空覆盖全部）。"""
    stmt = select(Entitlement).where(
        Entitlement.user_id == user_id,
        Entitlement.status == "active",
        Entitlement.ends_at > now,
        or_(Entitlement.photo_id == photo_id, Entitlement.photo_id.is_(None)),
    )
    return list(db.scalars(stmt))


def get_by_order_item(db: Session, order_item_id: int) -> Entitlement | None:
    return db.scalar(select(Entitlement).where(Entitlement.order_item_id == order_item_id))


def plan_names(db: Session, plan_ids: list[int]) -> dict[int, tuple[str, str]]:
    """plan_id → (code, name)，仅用于展示。"""
    if not plan_ids:
        return {}
    rows = db.execute(select(Plan.id, Plan.code, Plan.name).where(Plan.id.in_(plan_ids))).all()
    return {r.id: (r.code, r.name) for r in rows}


def quotas_by_entitlement(db: Session, entitlement_ids: list[int]) -> dict[int, EntitlementQuota]:
    """权益 ID → 回执额度行（内部用，ID 必须来自已按用户过滤的查询）。"""
    if not entitlement_ids:
        return {}
    rows = db.scalars(
        select(EntitlementQuota).where(
            EntitlementQuota.entitlement_id.in_(entitlement_ids),
            EntitlementQuota.benefit_type == RECEIPT_QUOTA,
        )
    )
    return {q.entitlement_id: q for q in rows}


def get_receipt_quota(db: Session, entitlement_id: int) -> EntitlementQuota | None:
    return quotas_by_entitlement(db, [entitlement_id]).get(entitlement_id)


def ledger_exists(db: Session, quota_id: int, action: str, application_id: int) -> bool:
    return (
        db.scalar(
            select(EntitlementLedger.id).where(
                EntitlementLedger.quota_id == quota_id,
                EntitlementLedger.action == action,
                EntitlementLedger.application_id == application_id,
            )
        )
        is not None
    )


def bump_photo_access_until(db: Session, photo_id: int, ends_at: datetime) -> None:
    """photos.access_until 取最晚值（冗余字段）。"""
    db.execute(
        update(Photo)
        .where(Photo.id == photo_id, or_(Photo.access_until.is_(None), Photo.access_until < ends_at))
        .values(access_until=ends_at)
        .execution_options(synchronize_session=False)
    )
