"""套餐、订单、支付。

- 对外函数 get_plan_by_code / get_plan_benefits / mark_paid 只 flush，不 commit。
- 接口入口函数（create_order、cancel_order、handle_wxpay_notify、simulate_paid 等）负责提交事务。
"""

import json
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.idempotency import run_idempotent
from app.core.utils import decode_cursor, encode_cursor, new_no, utcnow
from app.integrations.payment import get_payment
from app.models import Order, OrderItem, Payment, Plan, Refund
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
log = logging.getLogger("app.orders")


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


def close_expired(db: Session, limit: int = 100) -> int:
    """批量关闭过期的待支付订单及其待支付流水，返回订单数。"""
    now = utcnow()
    order_ids = repo.lock_expired_order_ids(db, now, limit)
    if order_ids:
        repo.close_expired(db, order_ids, now)
    db.commit()
    return len(order_ids)


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


def mark_paid(
    db: Session,
    *,
    out_trade_no: str,
    transaction_id: str,
    amount_fen: int,
    raw: dict,
    refund_closed: bool = True,
) -> Order:
    """支付成功入账。待支付订单发放权益，已关闭订单自动退款。幂等，不 commit。"""
    payment = repo.payment_by_out_trade_no(db, out_trade_no)
    if payment is None:
        raise AppError(ErrorCode.ORDER_NOT_FOUND)
    order = repo.lock_order(db, payment.order_id)
    payment = repo.lock_payment(db, payment.id)

    if payment.amount_fen != amount_fen:
        raise AppError(ErrorCode.ORDER_NOT_PAYABLE, "支付金额与订单金额不一致")
    if payment.status == "success":
        return order
    if order.status != "pending" and not (order.status == "closed" and refund_closed):
        raise AppError(ErrorCode.ORDER_NOT_PAYABLE)

    now = utcnow()
    payment.status = "success"
    payment.transaction_id = transaction_id
    payment.paid_at = now
    payment.raw = raw
    order.paid_fen = payment.amount_fen
    order.paid_at = now
    if order.status == "closed":
        db.flush()
        _refund_closed_payment(db, order, payment)
        return order

    order.status = "paid"
    db.flush()

    for item in repo.items_by_order(db, [order.id])[order.id]:
        plan = repo.get_plan(db, item.plan_id) if item.plan_id else None
        if plan is None:
            continue
        entitlement_service.grant_for_order_item(db, user_id=order.user_id, item=item, plan=plan, paid_at=now)
    return order


# ---------- 退款 ----------


@dataclass(frozen=True)
class RefundSubmission:
    """后台退款结果；重试已有退款时没有新的审计快照。"""

    refund: Refund
    order: Order
    before: dict[str, str | int] | None = None


def _submit_refund(db: Session, order: Order, payment: Payment, refund: Refund) -> None:
    """应用渠道受理结果。处理中占用可退余额，收到成功结果才更新订单和权益。"""
    result = get_payment().refund(
        out_trade_no=payment.out_trade_no,
        out_refund_no=refund.out_refund_no,
        refund_fen=refund.amount_fen,
        total_fen=payment.amount_fen,
        reason=refund.reason,
    )
    if result == "success":
        from app.modules.receipts import service as receipt_service

        refund.status = "success"
        refund.finished_at = utcnow()
        order.refunded_fen += refund.amount_fen
        order.status = "refunded" if order.refunded_fen == order.paid_fen else "part_refunded"
        if order.status == "refunded":
            entitlement_ids = entitlement_service.revoke_for_order(db, order.id)
            if entitlement_ids:
                receipt_service.cancel_for_refund(db, entitlement_ids)
    elif result == "failed":
        refund.status = "failed"
        refund.finished_at = utcnow()
    db.flush()


def _refund_closed_payment(db: Session, order: Order, payment: Payment) -> None:
    refund = repo.insert_refund(
        db,
        payment,
        out_refund_no=f"RL{payment.out_trade_no}",
        amount_fen=payment.amount_fen,
        reason="订单关闭后收到支付成功通知",
        operator="system",
    )
    if refund is None:
        return
    _submit_refund(db, order, payment, refund)
    # audit_logs 要求管理员外键；系统操作由退款流水持久记录，同时输出结构化字段。
    log.warning(
        "refund.auto_closed_order order_no=%s out_refund_no=%s amount_fen=%s status=%s",
        order.order_no,
        refund.out_refund_no,
        refund.amount_fen,
        refund.status,
    )


def _replay_refund(refund: Refund, order: Order, amount_fen: int) -> RefundSubmission:
    if refund.order_id != order.id or refund.amount_fen != amount_fen:
        raise AppError(ErrorCode.IDEMPOTENCY_CONFLICT)
    return RefundSubmission(refund, order)


def refund_order(
    db: Session, *, order_no: str, request_id: UUID, amount_fen: int, reason: str, operator: str
) -> RefundSubmission:
    """发起退款或返回已有记录。由后台调用方提交事务。"""
    out_refund_no = f"RA{request_id.hex}"
    order_id = repo.order_id_by_no(db, order_no)
    if order_id is None:
        if repo.refund_by_no(db, out_refund_no) is not None:
            raise AppError(ErrorCode.IDEMPOTENCY_CONFLICT)
        raise AppError(ErrorCode.ORDER_NOT_FOUND)
    order = repo.lock_order(db, order_id)
    existing = repo.refund_by_no(db, out_refund_no)
    if existing is not None:
        return _replay_refund(existing, order, amount_fen)
    if order.status not in ("paid", "part_refunded"):
        raise AppError(ErrorCode.REFUND_NOT_ALLOWED, "只有已支付或部分退款的订单可以退款")
    payment_id = repo.successful_payment_id(db, order.id)
    if payment_id is None:
        raise AppError(ErrorCode.REFUND_NOT_ALLOWED, "订单没有支付成功的流水")
    payment = repo.lock_payment(db, payment_id)

    refundable = order.paid_fen - order.refunded_fen - repo.pending_refund_fen(db, order.id)
    if amount_fen <= 0 or amount_fen > refundable:
        raise AppError(
            ErrorCode.REFUND_NOT_ALLOWED, f"退款金额必须大于 0 且不超过可退余额（{refundable} 分）"
        )

    refund = repo.insert_refund(
        db, payment, out_refund_no=out_refund_no, amount_fen=amount_fen, reason=reason, operator=operator
    )
    if refund is None:
        # 不同订单可并发使用同一个 UUID；唯一商户退款单号决定哪个请求先创建。
        existing = repo.refund_by_no(db, out_refund_no)
        assert existing is not None
        return _replay_refund(existing, order, amount_fen)
    before = {"status": order.status, "refunded_fen": order.refunded_fen}
    _submit_refund(db, order, payment, refund)
    return RefundSubmission(refund, order, before)


# ---------- 支付回调与联调 ----------


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
        refund_closed=False,
    )
    db.commit()
    return _orders_out(db, [order])[0]
