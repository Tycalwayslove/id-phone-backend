from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NotifyTask, UserIdentity
from app.modules.notify import service as notify_service
from tests.receipts.helpers import create_app, get_application, make_world, simulate

BASE = "/api/v1/notify"
RECEIPTS = "/api/v1/receipt-applications"


def _templates(client: TestClient, headers) -> dict[str, str]:
    r = client.get(f"{BASE}/templates", headers=headers)
    assert r.status_code == 200, r.text
    return {t["event"]: t["template_id"] for t in r.json()}


def _subscribe(client: TestClient, headers, ids: list[str]):
    return client.post(f"{BASE}/subscriptions", headers=headers, json={"accepted": ids})


def _tasks(db: Session, app_no: str, event: str) -> list[NotifyTask]:
    app_id = get_application(db, app_no).id
    return list(
        db.scalars(select(NotifyTask).where(NotifyTask.application_id == app_id, NotifyTask.event == event))
    )


def test_templates_require_login(client: TestClient):
    r = client.get(f"{BASE}/templates")
    assert r.status_code == 401
    assert r.json()["code"] == "AUTH_REQUIRED"


def test_templates_list(client: TestClient, db: Session):
    w = make_world(client, db)
    templates = _templates(client, w.headers)
    assert set(templates) == {"receipt_completed", "receipt_rejected"}


def test_report_subscriptions_counts(client: TestClient, db: Session):
    w = make_world(client, db)
    tid = _templates(client, w.headers)["receipt_rejected"]
    assert _subscribe(client, w.headers, [tid]).json() == {"quota": {tid: 1}}
    # 再授权一次累加；重复 ID 只计一次；未知 ID 忽略
    assert _subscribe(client, w.headers, [tid, tid, "UNKNOWN"]).json() == {"quota": {tid: 2}}
    identity = db.scalars(select(UserIdentity).where(UserIdentity.provider == "wx_mini")).first()
    db.refresh(identity)
    assert identity.subscribe_quota == {tid: 2}


def test_rejected_creates_task(client: TestClient, db: Session):
    w = make_world(client, db)
    app_no = create_app(client, w)["app_no"]
    simulate(client, w.headers, app_no, "rejected")
    tasks = _tasks(db, app_no, "receipt_rejected")
    assert len(tasks) == 1
    assert tasks[0].status == "pending"
    assert tasks[0].channel == "mini_subscribe" and tasks[0].step == 1


def test_completed_creates_task(client: TestClient, db: Session):
    w = make_world(client, db)
    app_no = create_app(client, w)["app_no"]
    simulate(client, w.headers, app_no, "completed")
    assert len(_tasks(db, app_no, "receipt_completed")) == 1


def test_send_due_sends_when_subscribed(client: TestClient, db: Session):
    w = make_world(client, db)
    tid = _templates(client, w.headers)["receipt_rejected"]
    _subscribe(client, w.headers, [tid])
    app_no = create_app(client, w)["app_no"]
    simulate(client, w.headers, app_no, "rejected")
    assert notify_service.send_due(db) == 1
    task = _tasks(db, app_no, "receipt_rejected")[0]
    assert task.status == "sent" and task.sent_at is not None
    assert task.result == {"mode": "fake"}
    assert _subscribe(client, w.headers, []).json() == {"quota": {tid: 0}}
    # 没有到期的任务时不再处理
    assert notify_service.send_due(db) == 0


def test_send_due_skips_without_subscription(client: TestClient, db: Session):
    w = make_world(client, db)
    app_no = create_app(client, w)["app_no"]
    simulate(client, w.headers, app_no, "rejected")
    assert notify_service.send_due(db) == 1
    task = _tasks(db, app_no, "receipt_rejected")[0]
    assert task.status == "skipped"
    assert task.result["reason"] == "no_subscribe_quota"


def test_second_rejection_reactivates_sent_task(client: TestClient, db: Session):
    w = make_world(client, db)
    tid = _templates(client, w.headers)["receipt_rejected"]
    _subscribe(client, w.headers, [tid])
    app_no = create_app(client, w)["app_no"]
    simulate(client, w.headers, app_no, "rejected")
    notify_service.send_due(db)
    assert _tasks(db, app_no, "receipt_rejected")[0].status == "sent"
    client.post(f"{RECEIPTS}/{app_no}/resubmit", headers=w.headers, json={})
    simulate(client, w.headers, app_no, "rejected")
    tasks = _tasks(db, app_no, "receipt_rejected")
    assert len(tasks) == 1 and tasks[0].status == "pending"
