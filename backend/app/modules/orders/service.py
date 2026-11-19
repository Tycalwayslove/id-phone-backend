"""套餐、订单、支付。

- 对外函数 get_plan_by_code / get_plan_benefits / mark_paid 只 flush，不 commit。
- 接口入口函数（create_order、cancel_order、handle_wxpay_notify、simulate_paid 等）负责提交事务。
"""

import json
import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.idempotency import run_idempotent
from app.core.utils import decode_cursor, encode_cursor, new_no, utcnow
from app.integrations.payment import get_payment
from app.models import Order, OrderItem, Payment, Plan
from app.modules.entitlements import service as entitlement_service
from app.modules.orders import repo
from app.modules.orders.schemas import (
    OrderCreatedOut,
    OrderCreateIn,
    OrderItemOut,
    OrderOut,
    OrderPage,
    PlanBenefitsOut,
    PlanOut,
    WxpayAck,
)

ORDER_TTL = timedelta(minutes=30)


# ---------- 套餐 ----------


def get_plan_by_code(db: Session, code: str) -> Plan:
    """取在售套餐，不存在、未上架或不在销售窗口内 → PLAN_NOT_AVAILABLE。"""
    plan = repo.get_on_sale_plan(db, code, utcnow())
    if plan is None:
        raise AppError(ErrorCode.PLAN_NOT_AVAILABLE)
    return plan


def get_plan_benefits(db: Session, plan_id: int) -> dict[str, int]:
    return repo.benefits_by_plan(db, [plan_id])[plan_id]


def _plan_out(plan: Plan, benefits: dict[str, int]) -> PlanOut:
    known = {k: v for k, v in benefits.items() if k in PlanBenefitsOut.model_fields}
    return PlanOut(
        code=plan.code,
        name=plan.name,
        price_fen=plan.price_fen,
        benefits=PlanBenefitsOut(**known),
        display=plan.display or {},
    )


def list_plans(db: Session) -> list[PlanOut]:
    plans = repo.list_on_sale_plans(db, utcnow())
    benefits = repo.benefits_by_plan(db, [p.id for p in plans])
    return [_plan_out(p, benefits[p.id]) for p in plans]


# ---------- 订单展示 ----------


def _orders_out(db: Session, orders: list[Order]) -> list[OrderOut]:
    items = repo.items_by_order(db, [o.id for o in orders])
    return [_order_out(o, items[o.id]) for o in orders]


def _order_out(order: Order, items: list[OrderItem]) -> OrderOut:
    return OrderOut(**_order_fields(order, items))


def _order_fields(order: Order, items: list[OrderItem]) -> dict:
    return dict(
        order_no=order.order_no,
        status=order.status,
        total_fen=order.total_fen,
        paid_fen=order.paid_fen,
        refunded_fen=order.refunded_fen,
        created_at=order.created_at,
        paid_at=order.paid_at,
        expire_at=order.expire_at,
        items=[
            OrderItemOut(
                item_type=it.item_type,
                plan_code=(it.snapshot or {}).get("plan_code"),
                plan_name=(it.snapshot or {}).get("plan_name"),
                photo_id=it.photo_id,
                amount_fen=it.amount_fen,
            )
            for it in items
        ],
    )


def _close_expired(db: Session, orders: list[Order]) -> None:
    """读取时就地关闭已超时的待支付订单。"""
    now = utcnow()
    expired = [o for o in orders if o.status == "pending" and o.expire_at <= now]
    if not expired:
        return
    repo.close_expired(db, [o.id for o in expired], now)
    db.commit()
    for o in expired:
        db.refresh(o)


# ---------- 下单 ----------


def create_order(db: Session, user_id: int, idem_key: str | None, payload: OrderCreateIn) -> OrderCreatedOut:
    return run_idempotent(
        db,
        user_id=user_id,
        scope="orders.create",
        key=idem_key,
        request=payload.model_dump(mode="json"),
        produce=lambda: _do_create_order(db, user_id, payload),
        out_model=OrderCreatedOut,
    )


def _do_create_order(db: Session, user_id: int, payload: OrderCreateIn) -> OrderCreatedOut:
    from app.modules.photos import service as photo_service  # 函数内导入，避免模块间循环依赖

    plan = get_plan_by_code(db, payload.plan_code)
    if plan.price_fen <= 0:
        raise AppError(ErrorCode.PLAN_NOT_AVAILABLE)
    benefits = get_plan_benefits(db, plan.id)
    is_addon = benefits.get("attach_to_parent") == 1

    photo_id: int | None = None
    parent_id: int | None = None
    if is_addon:
        if payload.parent_entitlement_id is None:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "加购项必须选择要附加的主权益（parent_entitlement_id）"
            )
        parent = entitlement_service.require_active_entitlement(db, user_id, payload.parent_entitlement_id)
        parent_id, photo_id = parent.id, parent.photo_id
    elif benefits.get("photo_scope") == 1:
        if payload.photo_id is None:
            raise AppError(ErrorCode.VALIDATION_ERROR, "该套餐需要选择一张照片（photo_id）")
        photo_id = photo_service.get_photo_for_user(db, user_id, payload.photo_id).id

    now = utcnow()
    order = Order(
        order_no=new_no("O"),
        user_id=user_id,
        total_fen=plan.price_fen,
        client="wx_mini",
        expire_at=now + ORDER_TTL,
    )
    db.add(order)
    db.flush()
    item = OrderItem(
        order_id=order.id,
        item_type="addon" if is_addon else "plan",
        plan_id=plan.id,
        photo_id=photo_id,
        quantity=1,
        unit_price_fen=plan.price_fen,
        amount_fen=plan.price_fen,
        snapshot={
            "plan_code": plan.code,
            "plan_name": plan.name,
            "price_fen": plan.price_fen,
            "benefits": benefits,
            "parent_entitlement_id": parent_id,
        },
    )
    payment = Payment(
        order_id=order.id,
        channel="wxpay",
        out_trade_no=new_no("P"),
        amount_fen=plan.price_fen,
        status="pending",
    )
    db.add_all([item, payment])
    db.flush()

    pay_params = get_payment().create_prepay(
        out_trade_no=payment.out_trade_no,
        amount_fen=payment.amount_fen,
        description=plan.name,
        openid=repo.wx_mini_openid(db, user_id),
    )
    db.refresh(order)  # 取数据库生成的 created_at
    return OrderCreatedOut(**_order_fields(order, [item]), pay_params=pay_params)


# ---------- 查询、取消 ----------


def list_orders(db: Session, user_id: int, cursor_str: str | None, limit: int):
    cursor = decode_cursor(cursor_str) or {}
    try:
        before_id = int(cursor["id"]) if "id" in cursor else None
    except TypeError, ValueError:
        before_id = None
    rows = repo.list_orders_for_user(db, user_id, before_id=before_id, limit=limit + 1)
    has_more = len(rows) > limit
    rows = rows[:limit]
    _close_expired(db, rows)
    next_cursor = encode_cursor({"id": rows[-1].id}) if has_more and rows else None
    return OrderPage(items=_orders_out(db, rows), next_cursor=next_cursor)


def get_order(db: Session, user_id: int, order_no: str) -> OrderOut:
    order = repo.get_order_for_user(db, user_id, order_no)
    if order is None:
        raise AppError(ErrorCode.ORDER_NOT_FOUND)
    _close_expired(db, [order])
    return _orders_out(db, [order])[0]


def cancel_order(db: Session, user_id: int, order_no: str) -> OrderOut:
    order = repo.get_order_for_user(db, user_id, order_no, for_update=True)
    if order is None:
        raise AppError(ErrorCode.ORDER_NOT_FOUND)
    if order.status != "pending":
        raise AppError(ErrorCode.ORDER_NOT_CANCELLABLE)
    order.status = "closed"
    repo.close_pending_payments(db, [order.id])
    db.commit()
    # TODO: 真实微信支付需要同时调用微信“关闭订单”接口，防止用户稍后仍能付款
    return _orders_out(db, [order])[0]


# ---------- 支付 ----------


def mark_paid(db: Session, *, out_trade_no: str, transaction_id: str, amount_fen: int, raw: dict) -> Order:
    """支付成功入账：幂等。订单变 paid，并为每个订单项发放权益。不 commit。"""
    payment = repo.payment_by_out_trade_no(db, out_trade_no)
    if payment is None:
        raise AppError(ErrorCode.ORDER_NOT_FOUND)
    order = repo.lock_order(db, payment.order_id)
    payment = repo.lock_payment(db, payment.id)

    if payment.status == "success":
        return order
    if payment.amount_fen != amount_fen:
        raise AppError(ErrorCode.ORDER_NOT_PAYABLE, "支付金额与订单金额不一致")
    if order.status != "pending":
        # TODO: 订单已关闭/已处理却收到支付，需要自动退款
        raise AppError(ErrorCode.ORDER_NOT_PAYABLE)

    now = utcnow()
    payment.status = "success"
    payment.transaction_id = transaction_id
    payment.paid_at = now
    payment.raw = raw
    order.status = "paid"
    order.paid_fen = payment.amount_fen
    order.paid_at = now
    db.flush()

    for item in repo.items_by_order(db, [order.id])[order.id]:
        plan = repo.get_plan(db, item.plan_id) if item.plan_id else None
        if plan is None:
            continue
        entitlement_service.grant_for_order_item(db, user_id=order.user_id, item=item, plan=plan, paid_at=now)
    return order


def handle_wxpay_notify(db: Session, headers: dict[str, str], body: bytes) -> WxpayAck:
    """处理微信支付通知：验签、入账、提交。签名错误 → PAYMENT_SIGNATURE_INVALID。"""
    try:
        notify = get_payment().parse_notify(headers, body)
    except (KeyError, TypeError, ValueError) as e:
        raise AppError(ErrorCode.VALIDATION_ERROR, "支付通知内容格式不正确") from e
    if notify.success:
        mark_paid(
            db,
            out_trade_no=notify.out_trade_no,
            transaction_id=notify.transaction_id,
            amount_fen=notify.amount_fen,
            raw=json.loads(json.dumps(notify.raw, default=str)),
        )
        db.commit()
    return WxpayAck(code="SUCCESS", message="成功")


def simulate_paid(db: Session, user_id: int, order_no: str) -> OrderOut:
    """联调用：等价于收到一笔成功的支付通知。"""
    order = repo.get_order_for_user(db, user_id, order_no)
    if order is None:
        raise AppError(ErrorCode.ORDER_NOT_FOUND)
    payment = repo.latest_payment(db, order.id)
    if payment is None:
        raise AppError(ErrorCode.ORDER_NOT_PAYABLE)
    order = mark_paid(
        db,
        out_trade_no=payment.out_trade_no,
        transaction_id="FAKE" + secrets.token_hex(8).upper(),
        amount_fen=payment.amount_fen,
        raw={"mode": "fake", "simulated": True},
    )
    db.commit()
    return _orders_out(db, [order])[0]
