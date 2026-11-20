from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core import security
from app.integrations.notify_channels import CHANNEL_ORDER
from app.integrations.wechat import DeliveryError
from app.models import NotifyTask, User, UserIdentity, WecomContact
from app.modules.notify import repo, service
from app.modules.users import service as users_service
from tests.conftest import login
from tests.factories import make_plan
from tests.orders.helpers import grant_plan, latest_user_id

NOW = datetime(2026, 1, 1, tzinfo=UTC)
ALL_CHANNELS = ",".join(CHANNEL_ORDER)
PHONE = "13800000000"


def _set_channels(monkeypatch, channels):
    monkeypatch.setattr(service.settings, "notify_channels", channels)


def _reminder_target(client, db):
    login(client)
    user_id = latest_user_id(db)
    entitlement = grant_plan(db, user_id, make_plan(db, "notify_delivery", 1000, {}))
    return dict(user_id=user_id, entitlement_id=entitlement.id, event="entitlement_expiring")


def _tasks(db):
    return list(
        db.scalars(select(NotifyTask).order_by(NotifyTask.id).execution_options(populate_existing=True))
    )


def test_retry_limit_preserves_quota_and_escalates_once(monkeypatch):
    db = Mock(spec=Session)
    clock = NOW
    monkeypatch.setattr(service, "utcnow", lambda: clock)
    _set_channels(monkeypatch, ALL_CHANNELS)
    task = NotifyTask(
        id=1,
        user_id=2,
        application_id=3,
        event="receipt_completed",
        channel="mini_subscribe",
        step=1,
        scheduled_at=clock,
        status="pending",
    )
    template_id = next(
        template.template_id for template in service.list_templates() if template.event == task.event
    )
    identity = UserIdentity(open_id="fake-openid", subscribe_quota={template_id: 1})
    monkeypatch.setattr(repo, "get_mini_identity", Mock(return_value=identity))
    monkeypatch.setattr(users_service, "is_active_user", Mock(return_value=True))
    next_channel = Mock(return_value=True)
    monkeypatch.setattr(repo, "insert_task_once", next_channel)

    def next_due(_db, cutoff, excluded_ids):
        if task.status == "pending" and task.scheduled_at <= cutoff and task.id not in excluded_ids:
            return task
        return None

    monkeypatch.setattr(repo, "next_due_task", next_due)
    adapter = Mock()
    adapter.send.side_effect = DeliveryError("network_error")
    monkeypatch.setattr(service, "get_channel", Mock(return_value=adapter))

    for attempts, delay in enumerate((60, 120), start=1):
        assert service.send_due(db, limit=1) == 1
        assert task.result == {"mode": "fake", "attempts": attempts, "reason": "network_error"}
        assert task.status == "pending"
        assert task.scheduled_at == clock + timedelta(seconds=delay)
        assert service.send_due(db) == 0
        next_channel.assert_not_called()
        clock = task.scheduled_at

    assert service.send_due(db, limit=1) == 1
    assert task.status == "failed"
    assert task.result["attempts"] == 3
    assert task.sent_at is None
    assert identity.subscribe_quota == {template_id: 1}
    assert service.send_due(db) == 0
    assert adapter.send.call_count == 3
    assert len({call.args[0].delivery_id for call in adapter.send.call_args_list}) == 1
    next_channel.assert_called_once_with(
        db,
        channel="mp_template",
        user_id=2,
        application_id=3,
        entitlement_id=None,
        event="receipt_completed",
        step=1,
        generation=0,
        scheduled_at=clock,
    )


def test_send_due_commits_each_task_and_ignores_rolled_back_row_until_next_run(monkeypatch, caplog):
    db = Mock(spec=Session)
    calls = []
    tasks = [NotifyTask(id=i, channel="mini_subscribe") for i in (1, 2, 3)]

    def next_due(_db, cutoff, excluded_ids):
        return next((task for task in tasks if task.id not in excluded_ids), None)

    def process(_db, task, enabled, cutoff):
        calls.append(task.id)
        if task.id == 2:
            raise RuntimeError("private upstream data")
        tasks.remove(task)

    db.commit.side_effect = lambda: calls.append("commit")
    db.rollback.side_effect = lambda: calls.append("rollback")
    monkeypatch.setattr(repo, "next_due_task", next_due)
    monkeypatch.setattr(service, "_process_task", process)

    assert service.send_due(db, limit=3) == 2
    assert calls == [1, "commit", 2, "rollback", 3, "commit"]
    assert "private upstream data" not in caplog.text


def test_users_service_reads_notification_phone(monkeypatch):
    db = Mock(spec=Session)
    phone_owner = User(id=2, phone_enc=security.encrypt(PHONE, "phone"))
    get_active_user = Mock(side_effect=(phone_owner, User(id=2, phone_enc=b"invalid"), None))
    monkeypatch.setattr(users_service.repo, "get_active_user", get_active_user)
    assert users_service.get_notification_phone(db, 2) == PHONE
    assert users_service.get_notification_phone(db, 2) is None
    assert users_service.get_notification_phone(db, 2) is None


def test_escalates_in_order_without_changing_step(client, db, monkeypatch):
    _set_channels(monkeypatch, ALL_CHANNELS)
    monkeypatch.setattr(service, "utcnow", lambda: NOW)
    target = _reminder_target(client, db)
    user_id = target["user_id"]
    user = db.get(User, user_id)
    user.phone_enc = security.encrypt(PHONE, "phone")
    db.add(UserIdentity(user_id=user_id, app_id="fake-mp", provider="wx_mp", open_id="fake-mp-openid"))
    db.add(
        WecomContact(
            user_id=user_id, external_userid="fake-contact", follow_userid="fake-staff", added_at=NOW
        )
    )
    db.commit()
    calls = []

    def get_channel(channel, mode):
        def send(message):
            calls.append((channel, message.recipient, message.step))
            if channel == "mp_template":
                raise DeliveryError("not_following_mp", "skipped")
            if channel == "wecom":
                raise DeliveryError("wecom_session_unavailable", "skipped")

        return Mock(send=send)

    monkeypatch.setattr(service, "get_channel", get_channel)
    assert service.create_task_once(db, **target, step=7)
    db.commit()
    assert service.send_due(db) == 4
    tasks = _tasks(db)
    assert [(task.channel, task.step, task.status) for task in tasks] == [
        ("mini_subscribe", 7, "skipped"),
        ("mp_template", 7, "skipped"),
        ("wecom", 7, "skipped"),
        ("sms", 7, "sent"),
    ]
    assert [task.result.get("reason") for task in tasks] == [
        "no_subscribe_quota",
        "not_following_mp",
        "wecom_session_unavailable",
        None,
    ]
    assert calls == [
        ("mp_template", "fake-mp-openid", 7),
        ("wecom", "fake-contact", 7),
        ("sms", PHONE, 7),
    ]

    # 同档任务和升级已经存在，重新调度起点也不会再发送短信。
    assert not service.create_task_once(db, **target, step=7)
    tasks[0].status = "pending"
    db.commit()
    assert service.send_due(db) == 1
    assert service.send_due(db) == 0
    assert len(calls) == 3
    assert len(_tasks(db)) == 4


def test_disabled_channels_and_missing_phone(client, db, monkeypatch):
    _set_channels(monkeypatch, "sms, wecom")
    monkeypatch.setattr(service, "utcnow", lambda: NOW)
    target = _reminder_target(client, db)
    db.add(
        WecomContact(
            user_id=target["user_id"],
            external_userid="removed-contact",
            follow_userid="fake-staff",
            added_at=NOW,
            removed_at=NOW,
        )
    )
    db.commit()
    get_channel = Mock()
    monkeypatch.setattr(service, "get_channel", get_channel)
    assert service.create_task_once(db, **target, step=1)
    db.commit()

    assert service.send_due(db) == 3
    assert [(task.channel, task.status, task.result["reason"]) for task in _tasks(db)] == [
        ("mini_subscribe", "skipped", "channel_disabled"),
        ("wecom", "skipped", "no_wecom_contact"),
        ("sms", "skipped", "no_phone"),
    ]
    get_channel.assert_not_called()


def test_new_occurrence_rearms_existing_fallback(client, db, monkeypatch):
    _set_channels(monkeypatch, "mini_subscribe,sms")
    monkeypatch.setattr(service, "utcnow", lambda: NOW)
    target = _reminder_target(client, db)
    user = db.get(User, target["user_id"])
    user.phone_enc = security.encrypt(PHONE, "phone")
    db.commit()
    adapter = Mock()
    monkeypatch.setattr(service, "get_channel", Mock(return_value=adapter))

    service.create_task(db, **target)
    db.commit()
    assert service.send_due(db) == 2
    sms_id = _tasks(db)[1].id
    service.create_task(db, **target)
    db.commit()
    assert service.send_due(db, limit=1) == 1
    assert _tasks(db)[1].status == "pending"

    # 再次触发时，旧轮次尚未发出的短信取消，随后复用同一任务行。
    service.create_task(db, **target)
    db.commit()
    assert _tasks(db)[1].status == "cancelled"
    assert service.send_due(db) == 2
    assert len(_tasks(db)) == 2
    assert _tasks(db)[1].id == sms_id and _tasks(db)[1].status == "sent"
    assert adapter.send.call_count == 2
    assert len({call.args[0].delivery_id for call in adapter.send.call_args_list}) == 2


def test_single_task_rollback_does_not_undo_other_tasks(client, db, monkeypatch, caplog):
    monkeypatch.setattr(service, "utcnow", lambda: NOW)
    target = _reminder_target(client, db)
    for step in (7, 3, 1):
        assert service.create_task_once(db, **target, step=step)
    db.commit()
    process = service._process_task

    def process_with_failure(session, task, enabled, cutoff):
        process(session, task, enabled, cutoff)
        if task.step == 3:
            session.flush()
            session.execute(text("SELECT 1 / 0"))

    monkeypatch.setattr(service, "_process_task", process_with_failure)
    assert service.send_due(db) == 2
    assert [(task.step, task.status) for task in _tasks(db)] == [
        (7, "skipped"),
        (3, "pending"),
        (1, "skipped"),
    ]
    assert "err=DataError" in caplog.text
    assert "SELECT" not in caplog.text

    monkeypatch.setattr(service, "_process_task", process)
    assert service.send_due(db) == 1
    assert service.send_due(db) == 0
