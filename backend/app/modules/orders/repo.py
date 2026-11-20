"""套餐、订单、支付的查询。C 端查询函数第一个参数是 user_id，查不到返回 None。

只带 order_id / out_trade_no 的函数是内部用（支付回调、批量补数据），不按用户过滤。
"""

from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Order, OrderItem, Payment, Plan, PlanBenefit, Refund, UserIdentity

# ---------- 套餐 ----------


def list_on_sale_plans(db: Session, now: datetime) -> list[Plan]:
    stmt = (
        select(Plan)
        .where(
            Plan.status == "on_sale",
            or_(Plan.sale_starts_at.is_(None), Plan.sale_starts_at <= now),
            or_(Plan.sale_ends_at.is_(None), Plan.sale_ends_at > now),
        )
        .order_by(Plan.sort, Plan.id)
    )
    return list(db.scalars(stmt))


def get_on_sale_plan(db: Session, code: str, now: datetime) -> Plan | None:
    stmt = select(Plan).where(
        Plan.code == code,
        Plan.status == "on_sale",
        or_(Plan.sale_starts_at.is_(None), Plan.sale_starts_at <= now),
        or_(Plan.sale_ends_at.is_(None), Plan.sale_ends_at > now),
    )
    return db.scalar(stmt)


def get_plan(db: Session, plan_id: int) -> Plan | None:
    return db.get(Plan, plan_id)


def benefits_by_plan(db: Session, plan_ids: list[int]) -> dict[int, dict[str, int]]:
    result: dict[int, dict[str, int]] = {pid: {} for pid in plan_ids}
    if not plan_ids:
        return result
    for b in db.scalars(select(PlanBenefit).where(PlanBenefit.plan_id.in_(plan_ids))):
        result[b.plan_id][b.benefit_type] = b.int_value
    return result


# ---------- 订单 ----------


def get_order_for_user(db: Session, user_id: int, order_no: str, *, for_update: bool = False) -> Order | None:
    stmt = select(Order).where(Order.order_no == order_no, Order.user_id == user_id)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return db.scalar(stmt)


def list_orders_for_user(db: Session, user_id: int, *, before_id: int | None, limit: int) -> list[Order]:
    stmt = select(Order).where(Order.user_id == user_id)
    if before_id is not None:
        stmt = stmt.where(Order.id < before_id)
    return list(db.scalars(stmt.order_by(Order.id.desc()).limit(limit)))


def items_by_order(db: Session, order_ids: list[int]) -> dict[int, list[OrderItem]]:
    result: dict[int, list[OrderItem]] = {oid: [] for oid in order_ids}
    if not order_ids:
        return result
    for it in db.scalars(select(OrderItem).where(OrderItem.order_id.in_(order_ids)).order_by(OrderItem.id)):
        result[it.order_id].append(it)
    return result


def lock_expired_order_ids(db: Session, now: datetime, limit: int) -> list[int]:
    stmt = (
        select(Order.id)
        .where(Order.status == "pending", Order.expire_at <= now)
        .order_by(Order.expire_at, Order.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(db.scalars(stmt))


def close_expired(db: Session, order_ids: list[int], now: datetime) -> None:
    """把仍为待支付且已过期的订单和它的待支付流水改为 closed（条件更新，避免覆盖刚支付成功的订单）。"""
    db.execute(
        update(Order)
        .where(Order.id.in_(order_ids), Order.status == "pending", Order.expire_at <= now)
        .values(status="closed")
        .execution_options(synchronize_session=False)
    )
    close_pending_payments(db, order_ids)


def close_pending_payments(db: Session, order_ids: list[int]) -> None:
    db.execute(
        update(Payment)
        .where(Payment.order_id.in_(order_ids), Payment.status == "pending")
        .values(status="closed")
        .execution_options(synchronize_session=False)
    )


def wx_mini_openid(db: Session, user_id: int) -> str:
    open_id = db.scalar(
        select(UserIdentity.open_id)
        .where(UserIdentity.user_id == user_id, UserIdentity.provider == "wx_mini")
        .order_by(UserIdentity.id)
        .limit(1)
    )
    return open_id or ""


# ---------- 支付 ----------


def latest_payment(db: Session, order_id: int) -> Payment | None:
    return db.scalar(select(Payment).where(Payment.order_id == order_id).order_by(Payment.id.desc()).limit(1))


def pending_payment_nos(db: Session, order_id: int) -> list[str]:
    return list(
        db.scalars(
            select(Payment.out_trade_no)
            .where(Payment.order_id == order_id, Payment.status == "pending")
            .order_by(Payment.id)
        )
    )


def payment_by_out_trade_no(db: Session, out_trade_no: str) -> Payment | None:
    return db.scalar(select(Payment).where(Payment.out_trade_no == out_trade_no))


def lock_order(db: Session, order_id: int) -> Order:
    """锁订单行并读最新值。加锁顺序统一：先订单、后支付流水。"""
    return db.execute(
        select(Order).where(Order.id == order_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one()


def lock_payment(db: Session, payment_id: int) -> Payment:
    return db.execute(
        select(Payment)
        .where(Payment.id == payment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()


# ---------- 退款 ----------


def order_id_by_no(db: Session, order_no: str) -> int | None:
    return db.scalar(select(Order.id).where(Order.order_no == order_no))


def successful_payment_id(db: Session, order_id: int) -> int | None:
    return db.scalar(
        select(Payment.id)
        .where(Payment.order_id == order_id, Payment.status == "success")
        .order_by(Payment.id.desc())
        .limit(1)
    )


def pending_refund_fen(db: Session, order_id: int) -> int:
    return db.scalar(
        select(func.coalesce(func.sum(Refund.amount_fen), 0)).where(
            Refund.order_id == order_id, Refund.status == "pending"
        )
    )


def refund_by_no(db: Session, out_refund_no: str) -> Refund | None:
    return db.scalar(select(Refund).where(Refund.out_refund_no == out_refund_no))


def due_pending_refunds(db: Session, before: datetime, limit: int) -> list[Refund]:
    stmt = (
        select(Refund)
        .where(Refund.status == "pending", Refund.updated_at <= before)
        .order_by(Refund.updated_at, Refund.id)
        .limit(limit)
    )
    return list(db.scalars(stmt))


def insert_refund(
    db: Session, payment: Payment, *, out_refund_no: str, amount_fen: int, reason: str, operator: str
) -> Refund | None:
    stmt = (
        insert(Refund)
        .values(
            payment_id=payment.id,
            order_id=payment.order_id,
            out_refund_no=out_refund_no,
            amount_fen=amount_fen,
            reason=reason,
            operator=operator,
        )
        .on_conflict_do_nothing(index_elements=[Refund.out_refund_no])
        .returning(Refund)
    )
    return db.scalar(stmt)
