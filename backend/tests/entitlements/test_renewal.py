from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models import Entitlement, OrderItem, Plan
from app.modules.entitlements import service

NOW = datetime(2026, 11, 19, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("status", "age", "addon", "allowed"),
    [
        ("active", timedelta(days=-1), False, True),
        ("active", timedelta(0), False, True),
        ("expired", timedelta(days=30), False, True),
        ("expired", timedelta(days=30, microseconds=1), False, False),
        ("revoked", timedelta(days=-1), False, False),
        ("active", timedelta(days=-1), True, False),
    ],
)
def test_renewal_grace_period(monkeypatch, status, age, addon, allowed):
    entitlement = Entitlement(
        status=status, ends_at=NOW - age, benefits_snapshot={"attach_to_parent": int(addon)}
    )
    db = Mock(spec=Session)
    get_for_user = Mock(return_value=entitlement)
    monkeypatch.setattr(service.repo, "get_for_user", get_for_user)
    if allowed:
        assert service.require_renewable_entitlement(db, 1, 2, at=NOW) is entitlement
    else:
        with pytest.raises(AppError) as exc:
            service.require_renewable_entitlement(db, 1, 2, at=NOW)
        assert exc.value.code == ErrorCode.ENTITLEMENT_EXPIRED
    get_for_user.assert_called_once_with(db, 1, 2)


def test_renewal_ledger_prevents_reapplying_same_order_item(monkeypatch):
    ends_at = NOW.astimezone(timezone(timedelta(hours=-8))) + timedelta(days=4)
    ent = Entitlement(id=2, status="active", ends_at=ends_at, photo_id=3, benefits_snapshot={})
    item = OrderItem(item_type="renew", snapshot={"renew_entitlement_id": 2, "benefits": {"storage_days": 5}})
    plan = Plan()
    db = Mock(spec=Session)
    get_for_user = Mock(return_value=ent)
    bump_photo = Mock()
    monkeypatch.setattr(service.repo, "get_for_user", get_for_user)
    monkeypatch.setattr(service.repo, "bump_photo_access_until", bump_photo)

    for _ in range(2):
        assert service.grant_for_order_item(db, user_id=1, item=item, plan=plan, paid_at=NOW) is ent

    expected_end = NOW + timedelta(days=9)
    assert ent.ends_at == expected_end
    assert item.snapshot["renewal_ledger"] == {
        "storage_days": 5,
        "previous_ends_at": ends_at.astimezone(UTC).isoformat(),
        "ends_at": expected_end.isoformat(),
        "applied_at": NOW.isoformat(),
    }
    get_for_user.assert_called_with(db, 1, 2, for_update=True)
    bump_photo.assert_called_once_with(db, 3, expected_end)
    db.flush.assert_called_once_with()
