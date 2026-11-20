from datetime import timedelta
from time import time
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentAdmin, current_admin
from app.core.utils import utcnow
from app.integrations.storage import url_signature
from app.main import app
from app.models import AuditLog, Channel, ClientApp, File, Photo, PhotoRender, User
from app.modules.photos import service as photo_service
from tests.admin.helpers import API, admin_login
from tests.factories import make_spec
from tests.orders.helpers import make_photo

QUALITY = {"level": "warn", "issues": [{"code": "too_dark", "message": "请换到光线充足的地方"}]}


def _add_user(db, **fields):
    user = User(**fields)
    db.add(user)
    db.flush()
    return user


def _assert_signed_url(url, file, start, end):
    parts = urlsplit(url)
    params = parse_qs(parts.query)
    expires = int(params["exp"][0])
    assert parts.path == f"/files/{file.storage_key}"
    assert start + 600 <= expires <= end + 600
    assert params["sig"] == [url_signature(file.storage_key, expires)]


def _make_file(db, user, kind, path, *, status="active"):
    file = File(
        user_id=user.id,
        kind=kind,
        storage_key=f"test/{path}",
        bucket="local",
        mime="image/png",
        size_bytes=1,
        status=status,
    )
    db.add(file)
    db.flush()
    return file


def test_photo_detail_enforces_permission_and_commits_audit_before_reply(monkeypatch):
    session = Mock(spec=Session)
    admin = CurrentAdmin(id=8, username="photo-operator", role="operator", session_id=7)
    photo = Photo(id=12, user_id=3, source="upload", status="active", original_file_id=4, created_at=utcnow())
    original = File(id=4, user_id=3, kind="original", status="active", storage_key="test/example.jpg")
    lookup = Mock(return_value=(photo, {original.id: original}, []))
    monkeypatch.setattr(photo_service, "get_admin_photo_detail", lookup)
    with (
        patch.dict(app.dependency_overrides, {get_db: lambda: session, current_admin: lambda: admin}),
        TestClient(app) as client,
    ):
        start = int(time())
        response = client.get(f"{API}/photos/{photo.id}")
        assert response.status_code == 200
        detail = response.json()
        _assert_signed_url(detail["original_url"], original, start, int(time()))
        assert detail["thumbnail_url"] and detail["matting_url"] is None
        log = session.add.call_args.args[0]
        assert (log.admin_id, log.action, log.target_type, log.target_id) == (
            admin.id,
            "photo.view",
            "photo",
            photo.id,
        )
        assert log.before is None and log.after is None
        session.commit.assert_called_once()

        admin.role = "finance"
        response = client.get(f"{API}/photos/{photo.id}")
        assert response.status_code == 403
        lookup.assert_called_once_with(session, photo_id=photo.id)
        session.commit.assert_called_once()


def test_client_apps_user_attribution_and_permissions(client, db):
    app = ClientApp(platform="wx_mini", app_id="wx-source-example", name="来源测试")
    other = ClientApp(platform="wx_mp", app_id="wx-source-example", name="同 ID 公众号")
    channel = Channel(code="store_qr", name="门店二维码", source_type="qr")
    db.add_all([app, other, channel])
    db.flush()
    user = _add_user(db, source_app_id=app.id, first_channel_id=channel.id)
    _add_user(db, source_app_id=app.id, status="cancelled")
    _add_user(db, source_app_id=other.id)

    operator = admin_login(client, db, "operator", "operator")
    response = client.get(f"{API}/client-apps", params={"page_size": 10})
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 2
    assert [(row["id"], row["user_count"]) for row in page["items"]] == [(other.id, 1), (app.id, 2)]
    response = client.patch(f"{API}/client-apps/{app.id}", headers=operator, json={"status": "disabled"})
    assert response.status_code == 403 and response.json()["code"] == "PERMISSION_DENIED"

    owner = admin_login(client, db, "owner", "owner")
    response = client.patch(
        f"{API}/client-apps/{app.id}", headers=owner, json={"name": "  门店小程序  ", "status": "disabled"}
    )
    assert response.status_code == 200 and response.json()["name"] == "门店小程序"
    assert response.json()["status"] == "disabled"
    assert response.json()["user_count"] == 2
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "client_app.update"))
    assert audit.before == {"name": "来源测试", "status": "active"}
    assert audit.after == {"name": "门店小程序", "status": "disabled"}

    detail = client.get(f"{API}/users/{user.id}").json()
    assert detail["source_app"] == {
        "id": app.id,
        "name": "门店小程序",
        "platform": "wx_mini",
        "app_id": "wx-source-example",
    }
    assert detail["first_channel_name"] == "门店二维码"
    filters = {"source_app_id": app.id, "status": "active"}
    listed = client.get(f"{API}/users", params=filters).json()["items"]
    searched = client.post(f"{API}/users/search", headers=owner, json=filters).json()["items"]
    assert listed == searched
    assert len(listed) == 1
    assert listed[0]["id"] == user.id and listed[0]["source_app"] == detail["source_app"]
    assert listed[0]["first_channel_name"] == detail["first_channel_name"]


def test_photos_filters_signed_links_and_view_audit(client, db):
    user = _add_user(db)
    other = _add_user(db)
    first, second, excluded, purged = [make_photo(db, uid) for uid in (user.id, user.id, other.id, user.id)]
    for photo in (first, second, excluded, purged):
        photo.quality = QUALITY
        photo.matting_level = "fine"
    purged.status = "purged"
    second.retain_until = utcnow() + timedelta(days=30)
    spec = make_spec(db)
    matting = _make_file(db, user, "matting", "current.png")
    preview = _make_file(db, user, "preview", "preview.png")
    expired_file = _make_file(db, user, "render", "removed.png", status="purged")
    second.matting_file_id = matting.id
    db.add_all(
        [
            PhotoRender(
                photo_id=second.id,
                spec_id=spec.id,
                file_id=preview.id,
                bg_color="#FFFFFF",
                beauty_level=2,
                watermarked=True,
            ),
            PhotoRender(
                photo_id=second.id,
                spec_id=spec.id,
                file_id=expired_file.id,
                bg_color="#FFFFFF",
                beauty_level=2,
                watermarked=False,
            ),
        ]
    )
    db.flush()
    admin_login(client, db, "operator", "operator")
    filters = {
        "user_id": user.id,
        "status": "active",
        "matting_level": "fine",
        "quality_level": "warn",
        "page_size": 10,
    }
    start = int(time())
    response = client.get(f"{API}/photos", params=filters)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    page = response.json()
    assert page["total"] == 2
    assert [item["id"] for item in page["items"]] == [second.id, first.id]
    assert page["items"][0]["retain_until"] is not None
    end = int(time())
    _assert_signed_url(page["items"][0]["thumbnail_url"], preview, start, end)
    _assert_signed_url(page["items"][1]["thumbnail_url"], db.get(File, first.original_file_id), start, end)
    assert client.get(f"{API}/photos", params={"quality_level": "ok"}).json()["items"] == []
    assert client.get(f"{API}/photos", params={"matting_level": "fast"}).json()["items"] == []
    removed = client.get(f"{API}/photos", params={"status": "purged"}).json()["items"][0]
    assert removed["id"] == purged.id and removed["thumbnail_url"] is None
    audit_query = select(AuditLog).where(AuditLog.action == "photo.view").order_by(AuditLog.id)
    assert list(db.scalars(audit_query)) == []

    start = int(time())
    response = client.get(f"{API}/photos/{second.id}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    detail = response.json()
    end = int(time())
    assert detail["quality"] == QUALITY
    _assert_signed_url(detail["original_url"], db.get(File, second.original_file_id), start, end)
    _assert_signed_url(detail["matting_url"], matting, start, end)
    removed_render, available_render = detail["renders"]
    assert removed_render["url"] is None and removed_render["watermarked"] is False
    assert available_render["spec_name"] == spec.name and available_render["bg_color"] == "#FFFFFF"
    assert available_render["beauty_level"] == 2 and available_render["watermarked"] is True
    assert available_render["created_at"]
    _assert_signed_url(available_render["url"], preview, start, end)

    assert client.get(f"{API}/photos/{second.id}").status_code == 200
    assert client.get(f"{API}/photos/9223372036854775807").json()["code"] == "PHOTO_NOT_FOUND"
    logs = list(db.scalars(audit_query))
    assert [(log.target_type, log.target_id) for log in logs] == [("photo", second.id)] * 2
    assert all(log.before is None and log.after is None for log in logs)


def test_recent_photos_and_finance_access(client, db):
    user = _add_user(db)
    other = _add_user(db)
    photos = [make_photo(db, user.id) for _ in range(13)]
    make_photo(db, other.id)
    admin_login(client, db, "operator", "operator")
    response = client.get(f"{API}/users/{user.id}")
    assert response.status_code == 200 and response.json()["id"] == user.id
    recent = response.json()["recent_photos"]
    assert [row["id"] for row in recent] == [photo.id for photo in reversed(photos[-12:])]
    assert all(row["user_id"] == user.id and row["thumbnail_url"] for row in recent)

    admin_login(client, db, "finance", "finance")
    for url in (f"{API}/photos", f"{API}/photos/{photos[-1].id}"):
        response = client.get(url)
        assert response.status_code == 403 and response.json()["code"] == "PERMISSION_DENIED"
    response = client.get(f"{API}/users/{user.id}")
    assert response.status_code == 200 and response.json()["recent_photos"] == []
    assert db.scalar(select(AuditLog).where(AuditLog.action == "photo.view")) is None
