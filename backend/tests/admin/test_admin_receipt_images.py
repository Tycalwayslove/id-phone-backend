from time import time
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentAdmin, current_admin
from app.core.utils import utcnow
from app.integrations.storage import LocalStorage, get_storage, url_signature
from app.main import app
from app.models import AuditLog, File, Photo, PhotoRender, ReceiptApplication, ReceiptAttempt, Spec
from app.modules.photos import service as photo_service
from app.modules.receipts import service as receipt_service
from tests.admin.helpers import API, admin_login
from tests.receipts.helpers import create_app, get_application, make_world, new_photo, simulate


def _assert_signed_url(url, file, start, end):
    parts = urlsplit(url)
    params = parse_qs(parts.query)
    expires = int(params["exp"][0])
    assert parts.path == f"/files/{file.storage_key}"
    assert start + 600 <= expires <= end + 600
    assert params["sig"] == [url_signature(file.storage_key, expires)]


def test_receipt_detail_images_permissions_missing_files_and_audit(monkeypatch, tmp_path):
    session = Mock(spec=Session)
    viewer = CurrentAdmin(id=8, username="operator", role="operator", session_id=7)
    now = utcnow()
    receipt = ReceiptApplication(
        id=10,
        user_id=3,
        photo_id=12,
        spec_id=2,
        entitlement_id=6,
        app_no="R20261118000001",
        receipt_file_id=40,
        status="completed",
        resubmit_count=1,
        created_at=now,
        updated_at=now,
    )
    quality = {"level": "warn", "issues": [{"code": "too_dark", "message": "光线偏暗"}]}
    photo = Photo(id=12, user_id=3, original_file_id=30, status="active", quality=quality)
    original, rejected_file, current_file, official_file = [
        File(id=id_, storage_key=f"test/{id_}.png", status="active", mime="image/png")
        for id_ in (30, 31, 32, 40)
    ]
    rejected, current = [
        PhotoRender(id=id_, bg_color="#FFFFFF", beauty_level=1, watermarked=False, created_at=now)
        for id_ in (21, 22)
    ]
    attempts = [
        (
            ReceiptAttempt(
                seq=1, status="rejected", is_current=False, render_id=21, reject_reason="背景不均匀"
            ),
            "fake",
        ),
        (ReceiptAttempt(seq=2, status="completed", is_current=True, render_id=22), "fake"),
    ]
    storage = LocalStorage(str(tmp_path))
    for file in (original, rejected_file, current_file, official_file):
        storage.put(file.storage_key, b"image", file.mime)
    monkeypatch.setattr(photo_service, "get_storage", lambda: storage)
    lookup = Mock(
        return_value=photo_service.AdminReceiptAssets(
            photo=photo,
            original=original,
            receipt=official_file,
            renders={
                21: (rejected, "广东身份证", rejected_file, "active"),
                22: (current, "广东身份证", current_file, "active"),
            },
        )
    )
    monkeypatch.setattr(photo_service, "get_admin_receipt_assets", lookup)
    spec = Spec(code="gd-idcard", name="广东身份证")
    monkeypatch.setattr(
        receipt_service,
        "get_admin_application_detail",
        Mock(return_value=(receipt, spec, False, {"name": "张*"}, attempts)),
    )
    with (
        patch.dict(app.dependency_overrides, {get_db: lambda: session, current_admin: lambda: viewer}),
        TestClient(app) as client,
    ):
        url = f"{API}/receipt-applications/{receipt.app_no}"
        start = int(time())
        response = client.get(url)
        end = int(time())
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        detail = response.json()
        assert detail["photo"]["id"] == photo.id and detail["photo"]["quality"] == quality
        _assert_signed_url(detail["photo"]["thumbnail_url"], original, start, end)
        _assert_signed_url(detail["receipt_image_url"], official_file, start, end)
        first, second = detail["attempts"]
        assert first["reject_reason"] == "背景不均匀" and second["is_current"]
        _assert_signed_url(first["render"]["url"], rejected_file, start, end)
        _assert_signed_url(second["render"]["url"], current_file, start, end)
        assert second["render"]["spec_name"] == spec.name
        assert second["render"]["beauty_level"] == 1 and not second["render"]["watermarked"]
        log = session.add.call_args.args[0]
        assert (log.admin_id, log.action, log.target_type, log.target_id) == (
            viewer.id,
            "application.view",
            "receipt_application",
            receipt.id,
        )
        assert log.before is None and log.after is None
        session.commit.assert_called_once()

        original.status = "purged"
        storage.delete(rejected_file.storage_key)
        storage.delete(official_file.storage_key)
        detail = client.get(url).json()
        assert detail["photo"]["thumbnail_url"] is None and detail["photo"]["missing_reason"] == "文件已清理"
        missing_render = detail["attempts"][0]["render"]
        assert missing_render["url"] is None and missing_render["missing_reason"] == "文件不存在"
        assert detail["attempts"][1]["render"]["url"]
        assert detail["receipt_image_url"] is None and detail["receipt_image_missing_reason"] == "文件不存在"

        monkeypatch.setattr(viewer, "can", lambda permission: permission == "application:read")
        response = client.get(url)
        assert response.status_code == 200
        detail = response.json()
        assert detail["form_masked"] == {"name": "张*"}
        assert detail["photo"] is None and detail["receipt_image_url"] is None
        assert detail["receipt_image_missing_reason"] is None
        assert all(attempt["render"] is None for attempt in detail["attempts"])
        assert lookup.call_count == 2 and session.commit.call_count == 3

        monkeypatch.setattr(viewer, "can", lambda permission: permission == "photo:read")
        assert client.get(url).status_code == 403
        assert lookup.call_count == 2 and session.commit.call_count == 3


def test_receipt_detail_reads_the_original_and_each_attempt_file(client, db):
    world = make_world(client, db)
    app_no = create_app(client, world)["app_no"]
    replacement_id = new_photo(client, world.headers)
    assert simulate(client, world.headers, app_no, "rejected", "背景不均匀").status_code == 200
    response = client.post(
        f"/api/v1/receipt-applications/{app_no}/resubmit",
        headers=world.headers,
        json={"photo_id": replacement_id},
    )
    assert response.status_code == 200, response.text
    assert simulate(client, world.headers, app_no, "completed").status_code == 200
    receipt = get_application(db, app_no)
    admin_login(client, db, "operator", "operator")
    start = int(time())
    response = client.get(f"{API}/receipt-applications/{app_no}")
    end = int(time())
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["photo"]["id"] == replacement_id
    original = db.get(File, db.get(Photo, replacement_id).original_file_id)
    _assert_signed_url(detail["photo"]["thumbnail_url"], original, start, end)
    _assert_signed_url(detail["receipt_image_url"], db.get(File, receipt.receipt_file_id), start, end)

    renders = db.scalars(
        select(PhotoRender)
        .join(ReceiptAttempt, ReceiptAttempt.render_id == PhotoRender.id)
        .where(ReceiptAttempt.application_id == receipt.id)
        .order_by(ReceiptAttempt.seq)
    ).all()
    assert [render.photo_id for render in renders] == [world.photo_id, replacement_id]
    for attempt, render in zip(detail["attempts"], renders, strict=True):
        assert attempt["render"]["id"] == render.id
        _assert_signed_url(attempt["render"]["url"], db.get(File, render.file_id), start, end)
    assert detail["attempts"][0]["reject_reason"] == "背景不均匀"
    logs = db.scalars(select(AuditLog).where(AuditLog.action == "application.view")).all()
    assert [(log.target_type, log.target_id) for log in logs] == [("receipt_application", receipt.id)]

    receipt_file = db.get(File, receipt.receipt_file_id)
    get_storage().delete(receipt_file.storage_key)
    detail = client.get(f"{API}/receipt-applications/{app_no}").json()
    assert detail["receipt_image_url"] is None and detail["receipt_image_missing_reason"] == "文件不存在"
