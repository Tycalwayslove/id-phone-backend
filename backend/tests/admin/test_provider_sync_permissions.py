from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.core.db import get_db
from app.core.deps import csrf_for
from app.core.security import hash_token
from app.core.utils import utcnow
from app.main import app
from app.modules.admin import service
from app.modules.specs.schemas import ProviderSyncResult


def test_sync_requires_login_write_permission_and_csrf(monkeypatch):
    token = "test-session-token"
    now = utcnow()
    session = SimpleNamespace(
        id=1,
        admin_id=1,
        revoked_at=None,
        expires_at=now + timedelta(hours=1),
        absolute_expires_at=now + timedelta(hours=2),
        last_seen_at=now,
    )
    admin = SimpleNamespace(id=1, username="operator", role="operator", status="active")
    db = SimpleNamespace(scalar=lambda _: session, get=lambda *_: admin)
    sync = Mock(return_value=ProviderSyncResult(created=0, updated=0, unchanged=0, disabled=0, items=[]))
    monkeypatch.setattr(service, "sync_provider_specs", sync)
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: db)
    path = "/api/v1/admin/providers/zheying/sync-specs"
    headers = {"X-CSRF-Token": csrf_for(hash_token(token))}

    with TestClient(app) as client:
        response = client.post(path)
        assert response.status_code == 401 and response.json()["code"] == "AUTH_REQUIRED"
        client.cookies.set("admin_session", token)
        response = client.post(path, headers=headers)
        assert response.status_code == 403 and response.json()["code"] == "PERMISSION_DENIED"
        admin.role = "owner"
        for missing_or_invalid in ({}, {"X-CSRF-Token": "invalid"}):
            response = client.post(path, headers=missing_or_invalid)
            assert response.status_code == 403 and response.json()["code"] == "PERMISSION_DENIED"
        sync.assert_not_called()

        response = client.post(path, headers=headers)
        assert response.status_code == 200, response.text
        sync.assert_called_once()
        assert sync.call_args.args[-1] == "zheying"
        assert sync.call_args.kwargs == {"auto_publish": True}
        response = client.post(path, params={"auto_publish": "false"}, headers=headers)
        assert response.status_code == 200, response.text
        assert sync.call_args.kwargs == {"auto_publish": False}

        preview = "/api/v1/admin/spec-regions"
        assert client.get(f"{preview}/440100").json() == {"region_name": "广州市"}
        assert client.get(f"{preview}/999999").json() == {"region_name": None}
        assert client.get(f"{preview}/invalid").status_code == 422
