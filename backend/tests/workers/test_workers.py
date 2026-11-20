from datetime import UTC, datetime, timedelta
from threading import Event
from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.db import engine
from app.core.utils import utcnow
from app.models import NotifyTask, Order, Payment
from app.modules.entitlements import service as entitlements
from app.modules.notify import service as notify
from app.modules.orders import service as orders
from app.workers import runner
from tests.conftest import login
from tests.factories import make_plan
from tests.orders.helpers import grant_plan, latest_user_id


def test_close_expired_orders(client: TestClient, db: Session):
    headers = login(client)
    plan = make_plan(db, "worker_order", 1000, {})

    def create_order() -> Order:
        response = client.post("/api/v1/orders", headers=headers, json={"plan_code": plan.code})
        assert response.status_code == 200, response.text
        return db.scalars(select(Order).where(Order.order_no == response.json()["order_no"])).one()

    older, expired, future, paid = [create_order() for _ in range(4)]
    response = client.post(f"/api/v1/dev/orders/{paid.order_no}/simulate-paid", headers=headers)
    assert response.status_code == 200, response.text

    now = utcnow()
    older.expire_at = now - timedelta(minutes=2)
    expired.expire_at = paid.expire_at = now - timedelta(minutes=1)
    db.commit()

    def order_and_payment_status(order: Order) -> tuple[str, str]:
        db.refresh(order)
        payment_status = db.scalars(select(Payment.status).where(Payment.order_id == order.id)).one()
        return order.status, payment_status

    assert orders.close_expired(db, limit=1) == 1
    assert order_and_payment_status(older) == ("closed", "closed")
    assert order_and_payment_status(expired) == ("pending", "pending")
    assert orders.close_expired(db) == 1
    assert order_and_payment_status(expired) == ("closed", "closed")
    assert order_and_payment_status(future) == ("pending", "pending")
    assert order_and_payment_status(paid) == ("paid", "success")
    assert orders.close_expired(db) == 0


def test_expiration_reminders_are_created_once_per_window(client: TestClient, db: Session, monkeypatch):
    login(client)
    user_id = latest_user_id(db)
    plan = make_plan(db, "worker_reminder", 1000, {"storage_days": 30})
    now = datetime(2026, 11, 19, tzinfo=UTC)
    entitlement = grant_plan(db, user_id, plan, paid_at=now - timedelta(days=23))
    grant_plan(db, user_id, plan, paid_at=now - timedelta(days=30))
    grant_plan(db, user_id, plan, paid_at=now - timedelta(days=27))
    revoked = grant_plan(db, user_id, plan, paid_at=now - timedelta(days=23))
    revoked.status = "revoked"
    db.commit()
    monkeypatch.setattr(entitlements, "utcnow", lambda: now)

    def reminders() -> list[tuple[int, int, str]]:
        return list(
            db.execute(
                select(NotifyTask.entitlement_id, NotifyTask.step, NotifyTask.status)
                .where(NotifyTask.event == "entitlement_expiring")
                .order_by(NotifyTask.step.desc())
            ).tuples()
        )

    assert entitlements.create_expiration_reminders(db) == 1
    assert entitlements.create_expiration_reminders(db) == 0
    assert reminders() == [(entitlement.id, 7, "pending")]
    assert notify.send_due(db) == 1
    assert entitlements.create_expiration_reminders(db) == 0
    assert reminders() == [(entitlement.id, 7, "skipped")]

    now += timedelta(days=6)
    assert entitlements.create_expiration_reminders(db) == 1
    assert entitlements.create_expiration_reminders(db) == 0
    assert reminders() == [(entitlement.id, 7, "skipped"), (entitlement.id, 1, "pending")]


def test_create_task_once_keeps_existing_result(client: TestClient, db: Session):
    login(client)
    user_id = latest_user_id(db)
    entitlement = grant_plan(db, user_id, make_plan(db, "notify_once", 1000, {}))
    fields = dict(user_id=user_id, entitlement_id=entitlement.id, event="entitlement_expiring", step=1)

    assert notify.create_task_once(db, **fields) is True
    task = db.scalars(select(NotifyTask).where(NotifyTask.entitlement_id == entitlement.id)).one()
    scheduled_at = task.scheduled_at
    task.status = "sent"
    task.sent_at = utcnow()
    task.result = {"mode": "fake"}
    sent_at = task.sent_at
    db.commit()

    assert notify.create_task_once(db, **fields) is False
    db.refresh(task)
    assert (task.status, task.scheduled_at, task.sent_at, task.result) == (
        "sent",
        scheduled_at,
        sent_at,
        {"mode": "fake"},
    )


def test_run_once_continues_after_task_raises(monkeypatch, caplog):
    calls = []
    db = Mock(spec=Session)
    db.rollback.side_effect = lambda: calls.append("rollback")

    def poll_due(session):
        assert session is db
        calls.append("poll")
        raise RuntimeError("sensitive payload")

    monkeypatch.setattr(runner.receipts, "poll_due", poll_due)
    monkeypatch.setattr(runner.notify, "send_due", lambda _: calls.append("send"))
    monkeypatch.setattr(runner.orders, "close_expired", lambda _: calls.append("close"))
    monkeypatch.setattr(runner.orders, "poll_pending_refunds", lambda _: calls.append("refunds"))
    monkeypatch.setattr(runner.entitlements, "create_expiration_reminders", lambda _: calls.append("remind"))
    monkeypatch.setattr(
        runner.photos, "purge_orphan_uploads", lambda _db, _before: calls.append("purge") or 0
    )

    runner.run_once(db)

    assert calls == ["poll", "rollback", "send", "close", "refunds", "remind", "purge"]
    assert "task=poll_due err=RuntimeError" in caplog.text
    assert "sensitive payload" not in caplog.text


def test_leader_lock_survives_task_commit_and_is_released(monkeypatch):
    stop = Event()
    params = {"key": runner.ADVISORY_LOCK_KEY}
    try_lock = text("SELECT pg_try_advisory_lock(:key)")
    unlock = text("SELECT pg_advisory_unlock(:key)")

    with engine.connect() as contender:

        def run_once(db: Session) -> None:
            db.execute(text("SELECT 1"))
            db.commit()
            acquired = contender.scalar(try_lock, params)
            if acquired:
                contender.execute(unlock, params)
            stop.set()
            assert acquired is False

        monkeypatch.setattr(runner, "run_once", run_once)
        runner._run_as_leader(stop, 60)

        assert stop.is_set()
        assert contender.scalar(try_lock, params) is True
        assert contender.scalar(unlock, params) is True
