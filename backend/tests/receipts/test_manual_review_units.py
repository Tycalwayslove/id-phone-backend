from unittest.mock import Mock

import pytest

from app.core.errors import AppError, ErrorCode
from app.models import ReceiptApplication, ReceiptAttempt
from app.modules.receipts import repo, service


def test_manual_review_uses_state_machine_and_preserves_attempt_metadata(monkeypatch):
    db = Mock()
    app = ReceiptApplication(id=1, app_no="R123", status="processing", entitlement_id=2)
    attempt = ReceiptAttempt(
        application_id=app.id,
        is_current=True,
        status="unknown",
        request_payload={repo.MANUAL_REVIEW_REQUIRED: True, "spec_code": "test_spec"},
    )
    get_app = Mock(return_value=app)
    release = Mock()
    monkeypatch.setattr(repo, "get_admin_application_by_no", get_app)
    monkeypatch.setattr(repo, "get_current_attempt", Mock(return_value=attempt))
    monkeypatch.setattr(repo, "get_application_by_id", Mock(return_value=app))
    monkeypatch.setattr(service.ent_service, "release_quota", release)

    assert service.resolve_manual_review(db, app_no=app.app_no, result="failed") == (app, "processing")

    get_app.assert_called_once_with(db, app.app_no, for_update=True)
    assert app.status == attempt.status == "failed"
    assert attempt.finished_at is not None and attempt.next_poll_at is None
    assert attempt.request_payload == {"spec_code": "test_spec"}
    release.assert_called_once_with(db, app.entitlement_id, app.id)
    db.commit.assert_not_called()


@pytest.mark.parametrize(
    ("app_status", "attempt_status", "flag"),
    [
        ("cancelled", "unknown", True),
        ("processing", "completed", True),
        ("processing", "unknown", False),
        ("processing", "unknown", "true"),
        ("processing", None, True),
    ],
)
def test_manual_review_rejects_ineligible_or_stale_application(monkeypatch, app_status, attempt_status, flag):
    db = Mock()
    app = ReceiptApplication(id=1, app_no="R123", status=app_status)
    payload = {repo.MANUAL_REVIEW_REQUIRED: flag}
    attempt = (
        ReceiptAttempt(application_id=app.id, is_current=True, status=attempt_status, request_payload=payload)
        if attempt_status
        else None
    )
    monkeypatch.setattr(repo, "get_admin_application_by_no", Mock(return_value=app))
    monkeypatch.setattr(repo, "get_current_attempt", Mock(return_value=attempt))
    monkeypatch.setattr(repo, "get_application_by_id", Mock(return_value=app))

    with pytest.raises(AppError) as caught:
        service.resolve_manual_review(db, app_no=app.app_no, result="failed")

    assert caught.value.code == ErrorCode.CONFLICT
    assert app.status == app_status
    if attempt is not None:
        assert attempt.status == attempt_status and attempt.request_payload == payload
    db.flush.assert_not_called()
