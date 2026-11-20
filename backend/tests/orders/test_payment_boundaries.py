from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock
from uuid import NAMESPACE_URL, uuid5

import pytest
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.integrations.payment import PayNotify
from app.models import Order, OrderItem, Payment, Plan, Refund
from app.modules.orders import service


def test_wechat_success_time_is_used_for_entitlement_fulfillment(monkeypatch):
    monkeypatch.setattr(service.settings, "pay_mode", "wechat")
    db = Mock(spec=Session)
    mark_paid = Mock()
    monkeypatch.setattr(service, "mark_paid", mark_paid)
    raw = {"success_time": "2026-11-19T19:59:59+08:00"}

    service._record_payment(db, PayNotify("P1", "WX1", 1000, True, raw))

    mark_paid.assert_called_once_with(
        db,
        out_trade_no="P1",
        transaction_id="WX1",
        amount_fen=1000,
        raw=raw,
        paid_at=datetime(2026, 11, 19, 11, 59, 59, tzinfo=UTC),
    )


@pytest.mark.parametrize("code", [ErrorCode.ENTITLEMENT_EXPIRED, ErrorCode.ENTITLEMENT_NOT_FOUND])
def test_invalid_addon_preserves_payment_and_requests_refund_once(monkeypatch, caplog, code):
    db = MagicMock(spec=Session)
    order = Order(id=1, order_no="O1", user_id=2, status="pending")
    payment = Payment(id=3, order_id=1, out_trade_no="P1", amount_fen=1000, status="pending")
    item = OrderItem(id=4, item_type="addon", plan_id=5, snapshot={"parent_entitlement_id": 6})
    refund = Refund(out_refund_no="RA1", amount_fen=1000, status="pending", operator="system")
    submission = service.RefundSubmission(refund, order, {"status": "paid", "refunded_fen": 0})
    refund_order = Mock(return_value=submission)
    monkeypatch.setattr(service.settings, "pay_mode", "wechat")
    monkeypatch.setattr(service.repo, "payment_by_out_trade_no", lambda *args: payment)
    monkeypatch.setattr(service.repo, "lock_order", lambda *args: order)
    monkeypatch.setattr(service.repo, "lock_payment", lambda *args: payment)
    monkeypatch.setattr(service.repo, "items_by_order", lambda *args: {order.id: [item]})
    monkeypatch.setattr(service.repo, "get_plan", lambda *args: Plan())
    monkeypatch.setattr(service.entitlement_service, "grant_for_order_item", Mock(side_effect=AppError(code)))
    monkeypatch.setattr(service, "refund_order", refund_order)

    for _ in range(2):
        result = service.mark_paid(db, out_trade_no="P1", transaction_id="WX1", amount_fen=1000, raw={})
        assert result is order

    db.begin_nested.return_value.__enter__.return_value.rollback.assert_called_once_with()
    assert payment.status == "success" and order.status == "paid" and order.paid_fen == 1000
    refund_order.assert_called_once_with(
        db,
        order_no="O1",
        request_id=uuid5(NAMESPACE_URL, "idphone:payment:P1:entitlement-unavailable"),
        amount_fen=1000,
        reason="加购付款时主权益已失效",
        operator="system",
        defer_submission=True,
    )
    assert "refund.auto_entitlement_unavailable" in caplog.text
