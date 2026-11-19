"""权益：发放、查询、回执额度的预占/确认/释放。

对外给其他模块调用的函数（grant/photo_access/pick/reserve 等）只 flush，不 commit，
由调用方的 service 入口统一提交。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.utils import utcnow
from app.models import Entitlement, EntitlementLedger, EntitlementQuota, OrderItem, Plan
from app.modules.entitlements import repo
from app.modules.entitlements.schemas import EntitlementOut

DEFAULT_STORAGE_DAYS = 30
LIST_LIMIT = 100


@dataclass(frozen=True)
class PhotoAccess:
    """某张照片当前的访问权限。"""

    active: bool
    access_until: datetime | None
    spec_change: bool


# ---------- 发放 ----------


def _benefits_of(db: Session, item: OrderItem, plan: Plan) -> dict[str, int]:
    """优先用下单时的权益快照；没有快照时读套餐当前配置。"""
    snap = (item.snapshot or {}).get("benefits")
    if isinstance(snap, dict) and snap:
        return {k: int(v) for k, v in snap.items()}
    from app.modules.orders import service as orders_service  # 函数内导入，避免循环依赖

    return orders_service.get_plan_benefits(db, plan.id)


def grant_for_order_item(
    db: Session, *, user_id: int, item: OrderItem, plan: Plan, paid_at: datetime
) -> Entitlement:
    """按订单项生成权益和额度。同一订单项重复调用返回已有权益。"""
    existing = repo.get_by_order_item(db, item.id)
    if existing is not None:
        return existing

    benefits = _benefits_of(db, item, plan)
    photo_id: int | None
    if benefits.get("attach_to_parent") == 1:
        parent_id = (item.snapshot or {}).get("parent_entitlement_id")
        parent = repo.get_for_user(db, user_id, int(parent_id)) if parent_id else None
        if parent is None:
            raise AppError(ErrorCode.ENTITLEMENT_NOT_FOUND)
        if parent.ends_at <= paid_at:
            # TODO: 付款时主权益已到期，需要人工或自动退款
            raise AppError(ErrorCode.ENTITLEMENT_EXPIRED)
        ends_at, photo_id = parent.ends_at, parent.photo_id
    else:
        days = benefits.get("storage_days") or DEFAULT_STORAGE_DAYS
        ends_at = paid_at + timedelta(days=days)
        photo_id = item.photo_id if benefits.get("photo_scope") == 1 else None

    ent = Entitlement(
        user_id=user_id,
        order_item_id=item.id,
        plan_id=plan.id,
        photo_id=photo_id,
        starts_at=paid_at,
        ends_at=ends_at,
        benefits_snapshot=benefits,
        status="active",
    )
    db.add(ent)
    db.flush()

    quota_total = benefits.get(repo.RECEIPT_QUOTA, 0)
    if quota_total > 0:
        db.add(
            EntitlementQuota(
                entitlement_id=ent.id, benefit_type=repo.RECEIPT_QUOTA, total=quota_total, used=0
            )
        )
        db.flush()

    if photo_id is not None:
        repo.bump_photo_access_until(db, photo_id, ends_at)
    return ent


def require_active_entitlement(db: Session, user_id: int, entitlement_id: int) -> Entitlement:
    """下单加购时校验主权益：必须是本人的、有效的。给 orders 模块调用。"""
    ent = repo.get_for_user(db, user_id, entitlement_id)
    if ent is None:
        raise AppError(ErrorCode.ENTITLEMENT_NOT_FOUND)
    if ent.status != "active" or ent.ends_at <= utcnow():
        raise AppError(ErrorCode.ENTITLEMENT_EXPIRED)
    return ent


# ---------- 查询 ----------


def photo_access(db: Session, user_id: int, photo_id: int) -> PhotoAccess:
    ents = repo.active_covering_photo(db, user_id, photo_id, utcnow())
    if not ents:
        return PhotoAccess(active=False, access_until=None, spec_change=False)
    return PhotoAccess(
        active=True,
        access_until=max(e.ends_at for e in ents),
        spec_change=any(e.benefits_snapshot.get("spec_change") == 1 for e in ents),
    )


def pick_for_receipt(db: Session, user_id: int, photo_id: int) -> Entitlement:
    """选覆盖该照片且回执额度有剩余的权益，到期早的优先。"""
    ents = repo.active_covering_photo(db, user_id, photo_id, utcnow())
    if not ents:
        raise AppError(ErrorCode.ENTITLEMENT_EXPIRED)
    quotas = repo.quotas_by_entitlement(db, [e.id for e in ents])
    usable = [e for e in ents if e.id in quotas and quotas[e.id].used < quotas[e.id].total]
    if not usable:
        raise AppError(ErrorCode.QUOTA_EXHAUSTED)
    return min(usable, key=lambda e: (e.ends_at, e.id))


def resubmit_limit(ent: Entitlement) -> int:
    return int(ent.benefits_snapshot.get("resubmit_limit", 0))


def bind_or_check_person(db: Session, ent: Entitlement, idcard_hash: str) -> None:
    """一卡一人：第一次绑定身份证哈希，之后不一致报错。非一卡一人权益不处理。"""
    if ent.benefits_snapshot.get("one_person") != 1:
        return
    if ent.bound_idcard_hash is None:
        # 条件更新防并发：只有仍为空时才写入
        res = db.execute(
            update(Entitlement)
            .where(Entitlement.id == ent.id, Entitlement.bound_idcard_hash.is_(None))
            .values(bound_idcard_hash=idcard_hash)
            .execution_options(synchronize_session=False)
        )
        db.refresh(ent)
        if res.rowcount == 1:
            return
    if ent.bound_idcard_hash != idcard_hash:
        raise AppError(ErrorCode.ONE_PERSON_MISMATCH)


# ---------- 回执额度 ----------


def _quota_of(db: Session, ent_id: int) -> EntitlementQuota:
    quota = repo.get_receipt_quota(db, ent_id)
    if quota is None:
        raise AppError(ErrorCode.QUOTA_EXHAUSTED)
    return quota


def reserve_quota(db: Session, ent_id: int, application_id: int) -> None:
    """预占一次回执额度。同一申请重复调用无副作用；额度不足 → QUOTA_EXHAUSTED。"""
    quota = _quota_of(db, ent_id)
    if repo.ledger_exists(db, quota.id, "reserve", application_id):
        return
    try:
        with db.begin_nested():
            res = db.execute(
                update(EntitlementQuota)
                .where(EntitlementQuota.id == quota.id, EntitlementQuota.used < EntitlementQuota.total)
                .values(used=EntitlementQuota.used + 1)
                .execution_options(synchronize_session=False)
            )
            if res.rowcount == 0:
                raise AppError(ErrorCode.QUOTA_EXHAUSTED)
            db.add(
                EntitlementLedger(quota_id=quota.id, application_id=application_id, action="reserve", delta=1)
            )
            db.flush()
    except IntegrityError:
        return  # 并发下另一个请求已经写入流水，保存点已回滚，used 不会多加
    db.refresh(quota)


def confirm_quota(db: Session, ent_id: int, application_id: int) -> None:
    """确认使用（回执成功）：只记流水，不改 used。需要先有预占，重复调用无副作用。"""
    quota = _quota_of(db, ent_id)
    if not repo.ledger_exists(db, quota.id, "reserve", application_id):
        return
    if repo.ledger_exists(db, quota.id, "confirm", application_id):
        return
    try:
        with db.begin_nested():
            db.add(
                EntitlementLedger(quota_id=quota.id, application_id=application_id, action="confirm", delta=0)
            )
            db.flush()
    except IntegrityError:
        return


def release_quota(db: Session, ent_id: int, application_id: int) -> None:
    """释放预占：只有存在预占且没释放过才 used-1，重复调用无副作用。"""
    quota = _quota_of(db, ent_id)
    if not repo.ledger_exists(db, quota.id, "reserve", application_id):
        return
    if repo.ledger_exists(db, quota.id, "release", application_id):
        return
    try:
        with db.begin_nested():
            db.execute(
                update(EntitlementQuota)
                .where(EntitlementQuota.id == quota.id, EntitlementQuota.used > 0)
                .values(used=EntitlementQuota.used - 1)
                .execution_options(synchronize_session=False)
            )
            db.add(
                EntitlementLedger(
                    quota_id=quota.id, application_id=application_id, action="release", delta=-1
                )
            )
            db.flush()
    except IntegrityError:
        return
    db.refresh(quota)


# ---------- 接口用 ----------


def _to_out(
    ent: Entitlement, names: dict[int, tuple[str, str]], quota: EntitlementQuota | None, now: datetime
) -> EntitlementOut:
    code, name = names.get(ent.plan_id, ("", ""))
    total = quota.total if quota else 0
    used = quota.used if quota else 0
    snap = ent.benefits_snapshot
    return EntitlementOut(
        id=ent.id,
        plan_code=code,
        plan_name=name,
        photo_id=ent.photo_id,
        starts_at=ent.starts_at,
        ends_at=ent.ends_at,
        is_active=ent.status == "active" and ent.ends_at > now,
        spec_change=snap.get("spec_change") == 1,
        one_person=snap.get("one_person") == 1,
        receipt_quota_total=total,
        receipt_quota_used=used,
        receipt_quota_left=max(total - used, 0),
        resubmit_limit=resubmit_limit(ent),
    )


def _to_outs(db: Session, ents: list[Entitlement]) -> list[EntitlementOut]:
    now = utcnow()
    names = repo.plan_names(db, list({e.plan_id for e in ents}))
    quotas = repo.quotas_by_entitlement(db, [e.id for e in ents])
    return [_to_out(e, names, quotas.get(e.id), now) for e in ents]


def list_entitlements(
    db: Session, user_id: int, status: Literal["active", "expired", "all"]
) -> list[EntitlementOut]:
    ents = repo.list_for_user(db, user_id, status=status, now=utcnow(), limit=LIST_LIMIT)
    return _to_outs(db, ents)


def get_entitlement(db: Session, user_id: int, entitlement_id: int) -> EntitlementOut:
    ent = repo.get_for_user(db, user_id, entitlement_id)
    if ent is None:
        raise AppError(ErrorCode.ENTITLEMENT_NOT_FOUND)
    return _to_outs(db, [ent])[0]
