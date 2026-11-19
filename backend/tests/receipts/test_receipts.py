import json

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.utils import utcnow
from app.integrations.receipt_providers import get_provider
from app.integrations.receipt_providers.fake import sign_fake_callback
from app.models import NotifyTask, ProviderCallback, ReceiptAttempt
from app.modules.receipts.poller import poll_due
from tests.factories import make_spec
from tests.receipts.helpers import (
    FAKE_IDCARD,
    PROVIDER_CODE,
    create_app,
    create_body,
    current_attempt,
    get_application,
    join_user,
    make_world,
    quota_used,
    simulate,
)

BASE = "/api/v1/receipt-applications"


def _reject_and_resubmit(client: TestClient, w, app_no: str) -> dict:
    assert simulate(client, w.headers, app_no, "rejected").status_code == 200
    r = client.post(f"{BASE}/{app_no}/resubmit", headers=w.headers, json={})
    assert r.status_code == 200, r.text
    return r.json()


def test_create_application_is_processing_and_masked(client: TestClient, db: Session):
    w = make_world(client, db)
    r = client.post(BASE, headers=w.headers, json=create_body(w))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "processing"
    assert body["resubmit_count"] == 0
    assert body["resubmit_left"] == 3
    assert body["receipt_url"] is None
    assert len(body["attempts"]) == 1 and body["attempts"][0]["status"] == "submitted"
    assert body["form_masked"]["name"] == "张*"
    assert body["form_masked"]["idcard"] == "110" + "*" * 11 + "0019"
    # 响应和库里的脱敏提交内容都不能带完整身份证号和姓名
    assert FAKE_IDCARD not in r.text
    payload = json.dumps(current_attempt(db, body["app_no"]).request_payload, ensure_ascii=False)
    assert FAKE_IDCARD not in payload and "张三" not in payload
    assert quota_used(db, get_application(db, body["app_no"]).entitlement_id) == 1


def test_create_is_idempotent_with_key(client: TestClient, db: Session):
    w = make_world(client, db)
    h = {**w.headers, "Idempotency-Key": "key-1"}
    a = client.post(BASE, headers=h, json=create_body(w)).json()
    b = client.post(BASE, headers=h, json=create_body(w)).json()
    assert a["app_no"] == b["app_no"]
    assert client.get(BASE, headers=w.headers).json()["items"].__len__() == 1


def test_simulate_completed(client: TestClient, db: Session):
    w = make_world(client, db)
    app_no = create_app(client, w)["app_no"]
    r = simulate(client, w.headers, app_no, "completed")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["image_code"]
    assert body["receipt_url"].startswith("http")
    assert body["completed_at"]
    assert body["attempts"][0]["status"] == "completed"
    assert quota_used(db, get_application(db, app_no).entitlement_id) == 1
    detail = client.get(f"{BASE}/{app_no}", headers=w.headers).json()
    assert detail["receipt_url"]


def test_simulate_rejected_keeps_quota_reserved(client: TestClient, db: Session):
    w = make_world(client, db)
    app_no = create_app(client, w)["app_no"]
    r = simulate(client, w.headers, app_no, "rejected", "背景不均匀")
    body = r.json()
    assert body["status"] == "rejected"
    assert body["reject_reason"] == "背景不均匀"
    assert body["rejected_at"]
    assert body["resubmit_left"] == 3
    assert quota_used(db, get_application(db, app_no).entitlement_id) == 1


def test_simulate_failed_releases_quota(client: TestClient, db: Session):
    w = make_world(client, db)
    app_no = create_app(client, w)["app_no"]
    assert simulate(client, w.headers, app_no, "failed").json()["status"] == "failed"
    assert quota_used(db, get_application(db, app_no).entitlement_id) == 0


def test_resubmit_after_reject(client: TestClient, db: Session):
    w = make_world(client, db)
    app_no = create_app(client, w)["app_no"]
    body = _reject_and_resubmit(client, w, app_no)
    assert body["status"] == "processing"
    assert body["resubmit_count"] == 1
    assert body["resubmit_left"] == 2
    assert body["reject_reason"] is None
    assert [a["seq"] for a in body["attempts"]] == [1, 2]
    assert body["attempts"][0]["status"] == "rejected"
    # 重提不再预占额度
    assert quota_used(db, get_application(db, app_no).entitlement_id) == 1
    # 重提后再出结果
    assert simulate(client, w.headers, app_no, "completed").json()["status"] == "completed"


def test_resubmit_requires_rejected(client: TestClient, db: Session):
    w = make_world(client, db)
    app_no = create_app(client, w)["app_no"]
    r = client.post(f"{BASE}/{app_no}/resubmit", headers=w.headers, json={})
    assert r.status_code == 409
    assert r.json()["code"] == "APPLICATION_NOT_RESUBMITTABLE"


def test_resubmit_limit_reached(client: TestClient, db: Session):
    w = make_world(client, db)
    app_no = create_app(client, w)["app_no"]
    for _ in range(3):
        _reject_and_resubmit(client, w, app_no)
    # 第 4 次驳回：重提次数已用完，额度最终释放，状态仍是 rejected
    body = simulate(client, w.headers, app_no, "rejected").json()
    assert body["status"] == "rejected"
    assert body["resubmit_left"] == 0
    assert quota_used(db, get_application(db, app_no).entitlement_id) == 0
    r = client.post(f"{BASE}/{app_no}/resubmit", headers=w.headers, json={})
    assert r.status_code == 409
    assert r.json()["code"] == "RESUBMIT_LIMIT_REACHED"


def test_resubmit_with_new_photo(client: TestClient, db: Session):
    from tests.receipts.helpers import new_photo

    w = make_world(client, db)
    app_no = create_app(client, w)["app_no"]
    new_id = new_photo(client, w.headers)
    simulate(client, w.headers, app_no, "rejected")
    r = client.post(f"{BASE}/{app_no}/resubmit", headers=w.headers, json={"photo_id": new_id})
    assert r.status_code == 200, r.text
    assert r.json()["photo_id"] == new_id


def test_resubmit_with_others_photo_rejected(client: TestClient, db: Session):
    w = make_world(client, db)
    bob = join_user(client, w.spec, user="dev:bob")
    app_no = create_app(client, w)["app_no"]
    simulate(client, w.headers, app_no, "rejected")
    r = client.post(f"{BASE}/{app_no}/resubmit", headers=w.headers, json={"photo_id": bob.photo_id})
    assert r.status_code == 404
    assert r.json()["code"] == "PHOTO_NOT_FOUND"


def test_spec_without_route_not_supported(client: TestClient, db: Session):
    w = make_world(client, db)
    other = make_spec(db, "rcp_no_route")
    r = client.post(BASE, headers=w.headers, json=create_body(w, spec_code=other.code))
    assert r.status_code == 409
    assert r.json()["code"] == "RECEIPT_NOT_SUPPORTED"


def test_missing_required_form_field(client: TestClient, db: Session):
    w = make_world(client, db)
    r = client.post(BASE, headers=w.headers, json=create_body(w, form={"name": "张三"}))
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"
    assert "身份证号" in r.json()["message"]


def test_bad_idcard_format(client: TestClient, db: Session):
    w = make_world(client, db)
    r = client.post(BASE, headers=w.headers, json=create_body(w, form={"name": "张三", "idcard": "123"}))
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_quota_exhausted_for_second_application(client: TestClient, db: Session):
    w = make_world(client, db)
    create_app(client, w)
    r = client.post(BASE, headers=w.headers, json=create_body(w))
    assert r.status_code == 409
    assert r.json()["code"] == "QUOTA_EXHAUSTED"


def test_other_users_application_not_found(client: TestClient, db: Session):
    w = make_world(client, db)
    bob = join_user(client, w.spec, user="dev:bob")
    app_no = create_app(client, w)["app_no"]
    for r in (
        client.get(f"{BASE}/{app_no}", headers=bob.headers),
        simulate(client, bob.headers, app_no, "completed"),
        client.post(f"{BASE}/{app_no}/cancel", headers=bob.headers),
        client.post(f"{BASE}/{app_no}/resubmit", headers=bob.headers, json={}),
    ):
        assert r.status_code == 404
        assert r.json()["code"] == "APPLICATION_NOT_FOUND"
    assert client.get(BASE, headers=bob.headers).json()["items"] == []


def test_requires_login(client: TestClient):
    r = client.get(BASE)
    assert r.status_code == 401
    assert r.json()["code"] == "AUTH_REQUIRED"


def test_cancel_rejected_releases_quota(client: TestClient, db: Session):
    w = make_world(client, db)
    app_no = create_app(client, w)["app_no"]
    simulate(client, w.headers, app_no, "rejected")
    ent_id = get_application(db, app_no).entitlement_id
    assert quota_used(db, ent_id) == 1
    r = client.post(f"{BASE}/{app_no}/cancel", headers=w.headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"
    assert quota_used(db, ent_id) == 0
    # 取消后不能再取消或重提
    r = client.post(f"{BASE}/{app_no}/cancel", headers=w.headers)
    assert r.json()["code"] == "APPLICATION_NOT_RESUBMITTABLE"


def test_cancel_processing_not_allowed(client: TestClient, db: Session):
    w = make_world(client, db)
    app_no = create_app(client, w)["app_no"]
    r = client.post(f"{BASE}/{app_no}/cancel", headers=w.headers)
    assert r.status_code == 409
    assert r.json()["code"] == "APPLICATION_NOT_RESUBMITTABLE"


# ---------- 回调 ----------


def _callback(client: TestClient, order_no: str, result: str, *, signature: str | None = None):
    body = json.dumps({"provider_order_no": order_no, "result": result}).encode()
    sig = signature if signature is not None else sign_fake_callback(body)
    return client.post(
        f"/api/v1/callbacks/receipt/{PROVIDER_CODE}",
        content=body,
        headers={"X-Fake-Signature": sig, "Content-Type": "application/json"},
    )


def test_callback_bad_signature_is_recorded_and_rejected(client: TestClient, db: Session):
    w = make_world(client, db)
    app_no = create_app(client, w)["app_no"]
    order_no = current_attempt(db, app_no).provider_order_no
    r = _callback(client, order_no, "completed", signature="bad")
    assert r.status_code == 401
    assert r.json()["code"] == "CALLBACK_SIGNATURE_INVALID"
    assert get_application(db, app_no).status == "processing"
    bad = db.scalar(
        select(func.count()).select_from(ProviderCallback).where(ProviderCallback.signature_ok.is_(False))
    )
    assert bad == 1


def test_callback_unknown_provider(client: TestClient):
    r = client.post("/api/v1/callbacks/receipt/nope", content=b"{}")
    assert r.status_code == 404


def test_callback_applied_once_when_sent_twice(client: TestClient, db: Session):
    w = make_world(client, db)
    app_no = create_app(client, w)["app_no"]
    attempt = current_attempt(db, app_no)
    r1 = _callback(client, attempt.provider_order_no, "rejected")
    r2 = _callback(client, attempt.provider_order_no, "rejected")
    assert r1.status_code == 200 and r1.json() == {"ok": True}
    assert r2.status_code == 200 and r2.json() == {"ok": True}
    assert get_application(db, app_no).status == "rejected"
    callbacks = db.scalars(select(ProviderCallback).where(ProviderCallback.attempt_id == attempt.id)).all()
    assert len(callbacks) == 1 and callbacks[0].process_result == "applied"
    tasks = db.scalars(
        select(NotifyTask).where(NotifyTask.application_id == get_application(db, app_no).id)
    ).all()
    assert len(tasks) == 1


def test_callback_for_unknown_order_is_unmatched(client: TestClient, db: Session):
    make_world(client, db)
    assert _callback(client, "NO-SUCH-ORDER", "completed").status_code == 200
    cb = db.scalars(
        select(ProviderCallback).where(ProviderCallback.provider_order_no == "NO-SUCH-ORDER")
    ).one()
    assert cb.process_result == "unmatched"


def test_old_attempt_callback_is_stale(client: TestClient, db: Session):
    w = make_world(client, db)
    app_no = create_app(client, w)["app_no"]
    old_order = current_attempt(db, app_no).provider_order_no
    simulate(client, w.headers, app_no, "rejected")
    client.post(f"{BASE}/{app_no}/resubmit", headers=w.headers, json={})
    assert _callback(client, old_order, "completed").status_code == 200
    # 旧提交晚到的结果不能覆盖当前状态
    assert get_application(db, app_no).status == "processing"


# ---------- 轮询 ----------


def test_poll_due_applies_provider_result(client: TestClient, db: Session):
    w = make_world(client, db)
    app_no = create_app(client, w)["app_no"]
    attempt = current_attempt(db, app_no)
    provider = get_provider("zheying", PROVIDER_CODE)
    provider.simulate(attempt.provider_order_no, "completed")
    attempt.next_poll_at = utcnow().replace(year=2020)
    db.flush()
    assert poll_due(db) == 1
    assert get_application(db, app_no).status == "completed"
    db.refresh(attempt)
    assert attempt.status == "completed"
    assert db.scalar(select(func.count()).select_from(ReceiptAttempt)) >= 1
