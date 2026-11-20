import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError, ErrorCode
from app.core.utils import new_no, utcnow
from app.models import EntitlementLedger, ReceiptApplication
from app.modules.entitlements import service
from tests.conftest import login
from tests.factories import make_plan, make_spec, make_standard_plans
from tests.orders.helpers import grant_plan, latest_user_id, make_photo

API = "/api/v1"


def _user(client, db, code="dev:alice"):
    h = login(client, code)
    return h, latest_user_id(db)


def _application(db, user_id, photo, ent) -> ReceiptApplication:
    spec = make_spec(db, f"spec_{uuid.uuid4().hex[:8]}")
    app = ReceiptApplication(
        app_no=new_no("R"), user_id=user_id, photo_id=photo.id, spec_id=spec.id, entitlement_id=ent.id
    )
    db.add(app)
    db.flush()
    return app


def _quota(db, ent):
    q = service.repo.get_receipt_quota(db, ent.id)
    db.refresh(q)
    return q


def _ledger_count(db, action):
    return db.scalar(
        select(func.count()).select_from(EntitlementLedger).where(EntitlementLedger.action == action)
    )


def test_list_and_detail_filters(client, db):
    plans = make_standard_plans(db)
    h, uid = _user(client, db)
    p1, p2 = make_photo(db, uid), make_photo(db, uid)
    live = grant_plan(db, uid, plans["photo_year_39_9"], photo_id=p1.id)
    old = grant_plan(
        db, uid, plans["photo_year_39_9"], photo_id=p2.id, paid_at=utcnow() - timedelta(days=400)
    )

    active = client.get(f"{API}/entitlements", headers=h).json()
    assert [e["id"] for e in active] == [live.id]
    expired = client.get(f"{API}/entitlements", params={"status": "expired"}, headers=h).json()
    assert [e["id"] for e in expired] == [old.id]
    assert expired[0]["is_active"] is False
    all_ = client.get(f"{API}/entitlements", params={"status": "all"}, headers=h).json()
    assert {e["id"] for e in all_} == {live.id, old.id}

    r = client.get(f"{API}/entitlements/{live.id}", headers=h)
    assert r.status_code == 200
    assert r.json()["plan_name"] == plans["photo_year_39_9"].name


def test_detail_of_others_or_missing_is_404(client, db):
    plans = make_standard_plans(db)
    _, uid = _user(client, db)
    ent = grant_plan(db, uid, plans["unlimited_99"])
    bob, _ = _user(client, db, "dev:bob")
    for eid in (ent.id, 99999999):
        r = client.get(f"{API}/entitlements/{eid}", headers=bob)
        assert r.status_code == 404
        assert r.json()["code"] == "ENTITLEMENT_NOT_FOUND"


def test_requires_login(client, db):
    assert client.get(f"{API}/entitlements").status_code == 401


def test_grant_defaults_and_idempotent(client, db):
    plans = make_standard_plans(db)
    _, uid = _user(client, db)
    no_days = make_plan(db, "no_days", 100, {"receipt_quota": 2})
    paid_at = utcnow()
    ent = grant_plan(db, uid, no_days, paid_at=paid_at)
    assert ent.ends_at == paid_at + timedelta(days=30)
    assert ent.photo_id is None

    ent99 = grant_plan(db, uid, plans["unlimited_99"], paid_at=paid_at)
    assert ent99.ends_at == paid_at + timedelta(days=365)
    assert ent99.benefits_snapshot["receipt_quota"] == 10


def test_photo_access(client, db):
    plans = make_standard_plans(db)
    _, uid = _user(client, db)
    p1, p2 = make_photo(db, uid), make_photo(db, uid)

    assert service.photo_access(db, uid, p1.id).active is False

    a = grant_plan(db, uid, plans["single_19_9"], photo_id=p1.id)  # 30 天，无换规格
    access = service.photo_access(db, uid, p1.id)
    assert access.active and access.access_until == a.ends_at and access.spec_change is False
    assert service.photo_access(db, uid, p2.id).active is False

    b = grant_plan(db, uid, plans["photo_year_39_9"], photo_id=p1.id)
    access = service.photo_access(db, uid, p1.id)
    assert access.access_until == b.ends_at and access.spec_change is True

    grant_plan(db, uid, plans["unlimited_99"])
    assert service.photo_access(db, uid, p2.id).active is True


def test_photo_access_ignores_expired(client, db):
    plans = make_standard_plans(db)
    _, uid = _user(client, db)
    p = make_photo(db, uid)
    grant_plan(db, uid, plans["photo_year_39_9"], photo_id=p.id, paid_at=utcnow() - timedelta(days=400))
    assert service.photo_access(db, uid, p.id).active is False


def test_photo_access_scoped_to_user(client, db):
    plans = make_standard_plans(db)
    _, alice = _user(client, db)
    grant_plan(db, alice, plans["unlimited_99"])
    _, bob = _user(client, db, "dev:bob")
    p = make_photo(db, bob)
    assert service.photo_access(db, bob, p.id).active is False


def test_photo_access_many_combines_coverage_and_ignores_inactive_and_foreign_grants(client, db):
    plans = make_standard_plans(db)
    _, uid = _user(client, db)
    _, other_uid = _user(client, db, "dev:bob")
    p1, p2, p3 = (make_photo(db, uid) for _ in range(3))
    global_plan = make_plan(db, "short_global", 100, {"storage_days": 7, "spec_change": 1})
    shared = grant_plan(db, uid, global_plan)
    scoped = grant_plan(db, uid, plans["single_19_9"], photo_id=p1.id)
    revoked = grant_plan(db, uid, plans["photo_year_39_9"], photo_id=p2.id)
    revoked.status = "revoked"
    grant_plan(db, uid, plans["photo_year_39_9"], photo_id=p3.id, paid_at=utcnow() - timedelta(days=400))
    grant_plan(db, other_uid, plans["unlimited_99"])
    db.flush()

    assert service.photo_access_many(db, uid, []) == {}
    assert service.photo_access_many(db, uid, [p1.id, p2.id, p3.id, p1.id]) == {
        p1.id: service.PhotoAccess(True, scoped.ends_at, True),
        p2.id: service.PhotoAccess(True, shared.ends_at, True),
        p3.id: service.PhotoAccess(True, shared.ends_at, True),
    }


def test_pick_for_receipt(client, db):
    plans = make_standard_plans(db)
    _, uid = _user(client, db)
    p = make_photo(db, uid)

    with pytest.raises(AppError) as ei:
        service.pick_for_receipt(db, uid, p.id)
    assert ei.value.code == ErrorCode.ENTITLEMENT_EXPIRED

    short = grant_plan(db, uid, plans["single_19_9"], photo_id=p.id)
    long_ = grant_plan(db, uid, plans["photo_year_39_9"], photo_id=p.id)
    assert service.pick_for_receipt(db, uid, p.id).id == short.id  # 到期早的优先

    service.reserve_quota(db, short.id, _application(db, uid, p, short).id)
    assert service.pick_for_receipt(db, uid, p.id).id == long_.id

    service.reserve_quota(db, long_.id, _application(db, uid, p, long_).id)
    with pytest.raises(AppError) as ei:
        service.pick_for_receipt(db, uid, p.id)
    assert ei.value.code == ErrorCode.QUOTA_EXHAUSTED


def test_resubmit_limit(client, db):
    plans = make_standard_plans(db)
    _, uid = _user(client, db)
    with_limit = grant_plan(db, uid, plans["photo_year_39_9"], photo_id=make_photo(db, uid).id)
    without = grant_plan(db, uid, make_plan(db, "no_resubmit", 1, {"receipt_quota": 1}))
    assert service.resubmit_limit(with_limit) == 3
    assert service.resubmit_limit(without) == 0


def test_reserve_confirm_release_flow(client, db):
    plans = make_standard_plans(db)
    _, uid = _user(client, db)
    p = make_photo(db, uid)
    ent = grant_plan(db, uid, plans["photo_year_39_9"], photo_id=p.id)  # 额度 1
    app1 = _application(db, uid, p, ent)
    app2 = _application(db, uid, p, ent)

    service.reserve_quota(db, ent.id, app1.id)
    service.reserve_quota(db, ent.id, app1.id)  # 重复：无副作用
    assert _quota(db, ent).used == 1
    assert _ledger_count(db, "reserve") == 1

    with pytest.raises(AppError) as ei:  # 额度只有 1，第二个申请预占失败
        service.reserve_quota(db, ent.id, app2.id)
    assert ei.value.code == ErrorCode.QUOTA_EXHAUSTED
    assert _quota(db, ent).used == 1
    assert _ledger_count(db, "reserve") == 1

    service.confirm_quota(db, ent.id, app1.id)
    service.confirm_quota(db, ent.id, app1.id)
    assert _quota(db, ent).used == 1
    assert _ledger_count(db, "confirm") == 1

    service.release_quota(db, ent.id, app1.id)
    service.release_quota(db, ent.id, app1.id)  # 重复释放不会多退
    assert _quota(db, ent).used == 0
    assert _ledger_count(db, "release") == 1

    service.release_quota(db, ent.id, app2.id)  # 没预占过，不退
    assert _quota(db, ent).used == 0
    assert _ledger_count(db, "release") == 1

    service.reserve_quota(db, ent.id, app2.id)  # 释放后别的申请可以再占
    assert _quota(db, ent).used == 1


def test_confirm_without_reserve_is_noop(client, db):
    plans = make_standard_plans(db)
    _, uid = _user(client, db)
    p = make_photo(db, uid)
    ent = grant_plan(db, uid, plans["photo_year_39_9"], photo_id=p.id)
    service.confirm_quota(db, ent.id, _application(db, uid, p, ent).id)
    assert _ledger_count(db, "confirm") == 0


def test_bind_or_check_person(client, db):
    plans = make_standard_plans(db)
    _, uid = _user(client, db)
    ent = grant_plan(db, uid, plans["unlimited_99"])
    service.bind_or_check_person(db, ent, "hash-a")
    assert ent.bound_idcard_hash == "hash-a"
    service.bind_or_check_person(db, ent, "hash-a")
    with pytest.raises(AppError) as ei:
        service.bind_or_check_person(db, ent, "hash-b")
    assert ei.value.code == ErrorCode.ONE_PERSON_MISMATCH

    single = grant_plan(db, uid, plans["photo_year_39_9"], photo_id=make_photo(db, uid).id)
    service.bind_or_check_person(db, single, "hash-a")
    service.bind_or_check_person(db, single, "hash-b")  # 非一卡一人，不绑定也不报错
    assert single.bound_idcard_hash is None
