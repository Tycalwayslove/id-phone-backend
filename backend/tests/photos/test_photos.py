import hashlib
import io
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest
from PIL import Image
from sqlalchemy import event, select

from app.core.config import settings
from app.core.deps import current_user
from app.core.utils import utcnow
from app.integrations import wechat
from app.integrations.storage import get_storage
from app.main import app
from app.models import File, Photo, PhotoRender, UserIdentity
from app.modules.photos import service as photo_service
from tests.conftest import login
from tests.factories import make_spec, make_standard_plans
from tests.orders.helpers import grant_plan
from tests.photos.helpers import jpeg_bytes, make_photo, png_rgba_bytes, set_access, upload

WECHAT_CALLBACK = "/api/v1/callbacks/wechat/media-check"


@pytest.fixture
def alice(client):
    return login(client, "dev:alice")


@pytest.fixture
def bob(client):
    return login(client, "dev:bob")


@pytest.fixture(autouse=True)
def no_access(monkeypatch):
    """默认没有权益；需要有权益的用例再调用 set_access 覆盖。"""
    set_access(monkeypatch, active=False)


@pytest.fixture
def real_media(client, db, alice, monkeypatch):
    # 在登录后换为真实模式；使用主会话约定提供的已验证 OpenID。
    monkeypatch.setattr(settings, "wechat_mode", "real")
    monkeypatch.setattr(settings, "wx_msg_token", "test-message-token")
    identity = db.scalar(select(UserIdentity).where(UserIdentity.open_id == "alice"))
    auth_user = SimpleNamespace(id=identity.user_id, wx_mini_open_id=identity.open_id)
    monkeypatch.setitem(app.dependency_overrides, current_user, lambda: auth_user)
    tasks = []

    def submit(*, media_url, open_id):
        assert open_id == "alice"
        url = urlparse(media_url)
        assert get_storage().get(url.path.removeprefix("/files/")) == jpeg_bytes()
        assert "sig=" in url.query
        tasks.append(f"trace-{len(tasks) + 1}")
        return tasks[-1]

    monkeypatch.setattr(wechat, "media_check_async", submit)
    return tasks


def wechat_callback(client, trace_id, *, suggest="pass", errcode=0, signature=None):
    timestamp, nonce = "1763452800", "98765"
    signed = "".join(sorted((settings.wx_msg_token, timestamp, nonce))).encode()
    response = client.post(
        WECHAT_CALLBACK,
        params={
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature or hashlib.sha1(signed).hexdigest(),
        },
        json={
            "MsgType": "event",
            "Event": "wxa_media_check",
            "appid": settings.wx_mini_app_id,
            "trace_id": trace_id,
            "errcode": errcode,
            "result": {"suggest": suggest},
        },
    )
    return response


def test_requires_login(client):
    for method, path in [
        ("get", "/api/v1/photos"),
        ("get", "/api/v1/photos/1"),
        ("delete", "/api/v1/photos/1"),
    ]:
        r = getattr(client, method)(path)
        assert r.status_code == 401
        assert r.json()["code"] == "AUTH_REQUIRED"
    assert (
        client.post("/api/v1/uploads", files={"file": ("a.jpg", jpeg_bytes(), "image/jpeg")}).status_code
        == 401
    )


def test_upload_rejects_invalid(client, alice):
    r = upload(client, alice, b"hello", name="a.txt", mime="text/plain")
    assert (r.status_code, r.json()["code"]) == (422, "UPLOAD_INVALID")
    # 声明是 jpeg，内容不是图片
    assert upload(client, alice, b"hello").json()["code"] == "UPLOAD_INVALID"
    # 太小
    assert upload(client, alice, jpeg_bytes(200, 200)).json()["code"] == "UPLOAD_INVALID"
    # 没有 file 字段
    r = client.post("/api/v1/uploads", data={"x": "1"}, headers=alice)
    assert r.json()["code"] == "UPLOAD_INVALID"


def test_upload_create_list(client, db, alice, monkeypatch):
    monkeypatch.setattr(photo_service.face_detection, "detect_faces", lambda _image: [])
    r = upload(client, alice)
    assert r.status_code == 200
    up = r.json()
    assert (up["width"], up["height"]) == (600, 800)
    assert client.get("/api/v1/photos", headers=alice).json()["items"] == []

    r = client.post("/api/v1/photos", json={"file_id": up["file_id"], "source": "camera"}, headers=alice)
    assert r.status_code == 200, r.text
    photo = r.json()
    assert photo["source"] == "camera" and photo["status"] == "active"
    assert photo["matting_level"] is None
    assert photo["access"]["active"] is False
    assert photo["quality"]["level"] == "fail"
    assert [issue["code"] for issue in photo["quality"]["issues"]] == ["no_face"]
    assert db.get(Photo, photo["id"]).quality == photo["quality"]

    items = client.get("/api/v1/photos", headers=alice).json()["items"]
    assert [i["id"] for i in items] == [photo["id"]]
    assert "renders" not in items[0]
    assert items[0]["quality"] == photo["quality"]
    detail = client.get(f"/api/v1/photos/{photo['id']}", headers=alice).json()
    assert detail["quality"] == photo["quality"]

    # 同一个文件不能再创建第二张照片
    r = client.post("/api/v1/photos", json={"file_id": up["file_id"], "source": "camera"}, headers=alice)
    assert r.json()["code"] == "UPLOAD_NOT_FOUND"


def test_create_saves_rgba_matting_and_render_uses_it(client, db, alice, monkeypatch):
    spec = make_spec(db, "ph_matte")
    set_access(monkeypatch, active=True)
    output = png_rgba_bytes()

    def matte(data):
        assert data == jpeg_bytes()
        return output

    monkeypatch.setattr(photo_service, "get_matting", lambda: SimpleNamespace(matte=matte))
    photo_id = make_photo(client, alice)
    photo = db.get(Photo, photo_id)
    assert photo.check_result == {"status": "passed"}
    matting = db.get(File, photo.matting_file_id)
    assert (matting.kind, matting.mime) == ("matting", "image/png")
    assert matting.storage_key == f"test/u{photo.user_id}/p{photo.id}/matting_f{matting.id}.png"
    assert get_storage().get(matting.storage_key) == output

    response = client.post(
        f"/api/v1/photos/{photo_id}/renders",
        json={"spec_code": spec.code, "bg_color": "#438EDB"},
        headers=alice,
    )
    assert response.status_code == 200, response.text
    url = urlparse(response.json()["preview_url"])
    image = client.get(f"{url.path}?{url.query}")
    with Image.open(io.BytesIO(image.content)) as rendered:
        assert rendered.getpixel((10, 10)) == pytest.approx((0x43, 0x8E, 0xDB), abs=3)


def test_blemish_points_distinguish_render_variants(client, db, alice):
    spec = make_spec(db, "ph_blemish")
    photo_id = make_photo(client, alice)
    path = f"/api/v1/photos/{photo_id}/renders"
    a, b = {"x": 0.4, "y": 0.5}, {"x": 0.5, "y": 0.6}

    def render(points):
        response = client.post(path, json={"spec_code": spec.code, "blemishes": points}, headers=alice)
        assert response.status_code == 200, response.text
        return response.json()["id"]

    plain = render([])
    edited = render([a, b])
    assert edited != plain
    assert render([b, a, b]) == edited
    assert render([a]) not in (plain, edited)
    assert render([]) == plain


@pytest.mark.parametrize("fine_succeeds", [True, False])
def test_fine_matting_updates_status_and_export_cache(
    client, db, alice, monkeypatch, tmp_path, caplog, fine_succeeds
):
    spec = make_spec(db, "ph_fine")
    monkeypatch.setattr(settings, "matting_mode", "local")
    monkeypatch.setattr(settings, "photo_models_dir", tmp_path)
    monkeypatch.setattr(photo_service.face_detection, "detect_faces", lambda _image: [])
    monkeypatch.setattr(
        photo_service, "get_matting", lambda: SimpleNamespace(matte=lambda _: png_rgba_bytes())
    )
    queued = []

    def queue(photo_id):
        assert not db.in_transaction()
        queued.append(photo_id)
        return True

    monkeypatch.setattr(photo_service, "_queue_fine_matting", queue)
    file_id = upload(client, alice).json()["file_id"]
    created = client.post("/api/v1/photos", json={"file_id": file_id, "source": "upload"}, headers=alice)
    assert created.status_code == 200, created.text
    photo_id = created.json()["id"]
    assert created.json()["matting_level"] == "fast"
    assert queued == [photo_id]
    photo = db.get(Photo, photo_id)
    fast_id = photo.matting_file_id

    path = f"/api/v1/photos/{photo_id}"

    def render():
        response = client.post(f"{path}/renders", json={"spec_code": spec.code}, headers=alice)
        assert response.status_code == 200, response.text
        return response.json()["id"]

    fast_render = render()
    assert render() == fast_render
    photo_service.recover_fine_matting(db)
    assert queued == [photo_id]
    photo.fine_matting_requested_at = utcnow() - timedelta(minutes=3)
    db.commit()
    photo_service.recover_fine_matting(db)
    assert queued == [photo_id, photo_id]

    if fine_succeeds:
        fine = png_rgba_bytes(400, 500)
        monkeypatch.setattr(photo_service.FineMatting, "matte", lambda self, data: fine)
    photo_service._process_fine_matting(db, photo_id)
    detail = client.get(path, headers=alice).json()
    assert detail["matting_level"] == ("fine" if fine_succeeds else "failed")
    assert photo.fine_matting_requested_at is None
    if fine_succeeds:
        assert photo.matting_file_id != fast_id and photo.previous_matting_file_id == fast_id
        fine_file = db.get(File, photo.matting_file_id)
        assert get_storage().get(fine_file.storage_key) == fine
        fine_render = render()
        assert fine_render != fast_render
        assert render() == fine_render
        photo_service._process_fine_matting(db, photo_id)
        assert photo.matting_file_id == fine_file.id
        assert client.delete(path, headers=alice).status_code == 200
        assert db.get(File, fast_id).status == fine_file.status == "purged"
    else:
        assert photo.matting_file_id == fast_id and render() == fast_render
        assert settings.fine_matting_model in caplog.text


@pytest.mark.parametrize("error", [TimeoutError, RuntimeError])
def test_matting_failure_falls_back_to_original(client, db, alice, monkeypatch, caplog, error):
    spec = make_spec(db, "ph_fallback")
    monkeypatch.setattr(settings, "matting_mode", "zheying")

    def matte(_data):
        raise error("upstream-private-detail")

    monkeypatch.setattr(photo_service, "get_matting", lambda: SimpleNamespace(matte=matte))
    photo_id = make_photo(client, alice)
    assert db.get(Photo, photo_id).matting_file_id is None
    assert "使用原图" in caplog.text
    assert "upstream-private-detail" not in caplog.text
    response = client.post(f"/api/v1/photos/{photo_id}/renders", json={"spec_code": spec.code}, headers=alice)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("callback_before_create", [True, False])
def test_wechat_callback_enables_render(client, db, alice, real_media, callback_before_create):
    spec = make_spec(db, "ph_checked")
    assert wechat_callback(client, "trace-1").status_code == 503
    original = upload(client, alice)
    assert original.status_code == 200, original.text
    assert real_media == ["trace-1"]
    file_id = original.json()["file_id"]
    draft = db.scalar(select(Photo).where(Photo.original_file_id == file_id))
    assert draft.check_result == {"status": "pending", "trace_id": "trace-1"}
    assert client.get("/api/v1/photos", headers=alice).json()["items"] == []
    if callback_before_create:
        assert wechat_callback(client, "trace-1").text == "success"

    response = client.post("/api/v1/photos", json={"file_id": file_id, "source": "camera"}, headers=alice)
    assert response.status_code == 200, response.text
    photo_id = response.json()["id"]
    assert photo_id == draft.id
    renders = f"/api/v1/photos/{photo_id}/renders"
    if not callback_before_create:
        assert response.json()["original_url"] == ""
        assert (
            client.post(renders, json={"spec_code": spec.code}, headers=alice).json()["code"]
            == "PHOTO_NOT_READY"
        )
        assert wechat_callback(client, "trace-1", signature="a" * 40).status_code == 401
        assert draft.check_result["status"] == "pending"
        assert wechat_callback(client, "trace-1").text == "success"
    detail = client.get(f"/api/v1/photos/{photo_id}", headers=alice).json()
    assert detail["original_url"]
    assert draft.check_result == {"status": "passed", "trace_id": "trace-1"}
    assert client.post(renders, json={"spec_code": spec.code}, headers=alice).status_code == 200


@pytest.mark.parametrize(
    ("suggest", "errcode", "stored_status", "error_code"),
    [
        ("review", 0, "rejected", "PHOTO_REJECTED"),
        ("risky", 0, "rejected", "PHOTO_REJECTED"),
        ("pass", -1008, "failed", "PHOTO_NOT_READY"),
    ],
)
def test_wechat_nonpassing_result_blocks_export_and_download(
    client, db, alice, real_media, monkeypatch, suggest, errcode, stored_status, error_code
):
    set_access(monkeypatch, active=True)
    spec = make_spec(db, "ph_rejected")
    photo_id = make_photo(client, alice)
    photo = db.get(Photo, photo_id)
    file = photo_service.save_file(
        db,
        user_id=photo.user_id,
        kind="render",
        data=jpeg_bytes(),
        mime="image/jpeg",
        ext="jpg",
        owner=f"p{photo_id}",
    )
    cached = PhotoRender(
        photo_id=photo_id, spec_id=spec.id, file_id=file.id, bg_color="#FFFFFF", watermarked=False
    )
    db.add(cached)
    db.flush()
    assert wechat_callback(client, real_media[0], suggest=suggest, errcode=errcode).text == "success"
    assert wechat_callback(client, real_media[0]).text == "success"
    assert photo.check_result["status"] == stored_status

    path = f"/api/v1/photos/{photo_id}"
    rendered = client.post(f"{path}/renders", json={"spec_code": spec.code}, headers=alice)
    downloaded = client.get(f"{path}/renders/{cached.id}/download", headers=alice)
    assert rendered.json()["code"] == downloaded.json()["code"] == error_code
    detail = client.get(path, headers=alice).json()
    assert detail["original_url"] == "" and detail["renders"] == []


def test_wechat_submission_failure_rolls_back_upload(client, db, alice, real_media, monkeypatch):
    keys = []

    def submit(*, media_url, open_id):
        keys.append(urlparse(media_url).path.removeprefix("/files/"))
        raise wechat.DeliveryError("network_error")

    monkeypatch.setattr(wechat, "media_check_async", submit)
    response = upload(client, alice)
    assert (response.status_code, response.json()["code"]) == (503, "PROVIDER_UNAVAILABLE")
    assert db.scalar(select(File).where(File.storage_key == keys[0])) is None
    with pytest.raises(FileNotFoundError):
        get_storage().get(keys[0])


def test_list_pagination_newest_first(client, alice):
    ids = [make_photo(client, alice) for _ in range(3)]
    p1 = client.get("/api/v1/photos", params={"limit": 2}, headers=alice).json()
    assert [i["id"] for i in p1["items"]] == [ids[2], ids[1]]
    p2 = client.get("/api/v1/photos", params={"limit": 2, "cursor": p1["next_cursor"]}, headers=alice).json()
    assert [i["id"] for i in p2["items"]] == [ids[0]]
    assert p2["next_cursor"] is None


def test_photo_list_loads_access_in_one_query(client, db, alice):
    plans = make_standard_plans(db)
    photo_ids = [make_photo(client, alice) for _ in range(3)]
    user_id = db.get(Photo, photo_ids[0]).user_id
    grant_plan(db, user_id, plans["photo_year_39_9"], photo_id=photo_ids[0])
    grant_plan(db, user_id, plans["single_19_9"], photo_id=photo_ids[1])
    queries = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "FROM entitlements" in statement:
            queries.append(statement)

    connection = db.connection()
    event.listen(connection, "before_cursor_execute", capture)
    try:
        response = client.get("/api/v1/photos", headers=alice)
    finally:
        event.remove(connection, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    assert len(queries) == 1
    access = {item["id"]: item["access"] for item in response.json()["items"]}
    assert [access[pid]["active"] for pid in photo_ids] == [True, True, False]
    assert [access[pid]["spec_change"] for pid in photo_ids] == [True, False, False]


def test_other_users_cannot_access(client, alice, bob):
    pid = make_photo(client, alice)
    for method, path, kw in [
        ("get", f"/api/v1/photos/{pid}", {}),
        ("delete", f"/api/v1/photos/{pid}", {}),
        ("post", f"/api/v1/photos/{pid}/renders", {"json": {"spec_code": "whatever"}}),
        ("get", f"/api/v1/photos/{pid}/renders/1/download", {}),
    ]:
        r = getattr(client, method)(path, headers=bob, **kw)
        assert (r.status_code, r.json()["code"]) == (404, "PHOTO_NOT_FOUND"), path
    assert client.get("/api/v1/photos", headers=bob).json()["items"] == []

    # 用别人的 file_id 建照片
    file_id = upload(client, alice).json()["file_id"]
    r = client.post("/api/v1/photos", json={"file_id": file_id, "source": "upload"}, headers=bob)
    assert r.json()["code"] == "UPLOAD_NOT_FOUND"


def test_render_without_access_is_watermarked_and_not_downloadable(client, db, alice):
    make_spec(db, "ph_a")
    pid = make_photo(client, alice)

    r = client.post(f"/api/v1/photos/{pid}/renders", json={"spec_code": "ph_a"}, headers=alice)
    assert r.status_code == 200, r.text
    rd = r.json()
    assert rd["watermarked"] is True
    assert rd["bg_color"] == "#FFFFFF"
    assert (rd["width_px"], rd["height_px"]) == (358, 441)

    # 相同参数复用
    again = client.post(f"/api/v1/photos/{pid}/renders", json={"spec_code": "ph_a"}, headers=alice).json()
    assert again["id"] == rd["id"]

    detail = client.get(f"/api/v1/photos/{pid}", headers=alice).json()
    assert [x["id"] for x in detail["renders"]] == [rd["id"]]

    r = client.get(f"/api/v1/photos/{pid}/renders/{rd['id']}/download", headers=alice)
    assert (r.status_code, r.json()["code"]) == (403, "PHOTO_ACCESS_EXPIRED")


def test_render_with_access_download(client, db, alice, monkeypatch):
    make_spec(db, "ph_b")
    pid = make_photo(client, alice)
    set_access(monkeypatch, active=True)

    rd = client.post(
        f"/api/v1/photos/{pid}/renders", json={"spec_code": "ph_b", "bg_color": "#438edb"}, headers=alice
    ).json()
    assert rd["watermarked"] is False
    assert rd["bg_color"] == "#438EDB"

    r = client.get(f"/api/v1/photos/{pid}/renders/{rd['id']}/download", headers=alice)
    assert r.status_code == 200
    url = urlparse(r.json()["url"])
    img_resp = client.get(f"{url.path}?{url.query}")
    assert img_resp.status_code == 200
    assert img_resp.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(img_resp.content)).size == (358, 441)

    # 权益过期后：详情里不再出现无水印图，也不能下载
    set_access(monkeypatch, active=False)
    detail = client.get(f"/api/v1/photos/{pid}", headers=alice).json()
    assert detail["renders"] == []
    r = client.get(f"/api/v1/photos/{pid}/renders/{rd['id']}/download", headers=alice)
    assert r.json()["code"] == "PHOTO_ACCESS_EXPIRED"


def test_watermarked_render_not_downloadable_even_with_access(client, db, alice, monkeypatch):
    make_spec(db, "ph_c")
    pid = make_photo(client, alice)
    rd = client.post(f"/api/v1/photos/{pid}/renders", json={"spec_code": "ph_c"}, headers=alice).json()
    assert rd["watermarked"] is True
    set_access(monkeypatch, active=True)
    r = client.get(f"/api/v1/photos/{pid}/renders/{rd['id']}/download", headers=alice)
    assert r.json()["code"] == "PHOTO_ACCESS_EXPIRED"


def test_spec_change_not_allowed(client, db, alice, monkeypatch):
    make_spec(db, "ph_d1")
    make_spec(db, "ph_d2")
    pid = make_photo(client, alice)
    set_access(monkeypatch, active=True, spec_change=False)

    assert (
        client.post(f"/api/v1/photos/{pid}/renders", json={"spec_code": "ph_d1"}, headers=alice).status_code
        == 200
    )
    # 同规格换底色允许
    r = client.post(
        f"/api/v1/photos/{pid}/renders", json={"spec_code": "ph_d1", "bg_color": "#438EDB"}, headers=alice
    )
    assert r.status_code == 200
    r = client.post(f"/api/v1/photos/{pid}/renders", json={"spec_code": "ph_d2"}, headers=alice)
    assert (r.status_code, r.json()["code"]) == (403, "SPEC_CHANGE_NOT_ALLOWED")

    # 允许换规格时可以
    set_access(monkeypatch, active=True, spec_change=True)
    assert (
        client.post(f"/api/v1/photos/{pid}/renders", json={"spec_code": "ph_d2"}, headers=alice).status_code
        == 200
    )


def test_render_validation(client, db, alice):
    make_spec(db, "ph_e")  # bg_colors 白/蓝，beauty_max=3
    pid = make_photo(client, alice)
    url = f"/api/v1/photos/{pid}/renders"
    assert client.post(url, json={"spec_code": "nope"}, headers=alice).json()["code"] == "SPEC_NOT_FOUND"
    r = client.post(url, json={"spec_code": "ph_e", "bg_color": "#000000"}, headers=alice)
    assert (r.status_code, r.json()["code"]) == (422, "VALIDATION_ERROR")
    r = client.post(url, json={"spec_code": "ph_e", "beauty_level": 4}, headers=alice)
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_render_normalizes_legacy_spec_colors_before_cache_lookup(client, db, alice):
    spec = make_spec(db, "ph_legacy_colors", bg_colors=["blue", "white", "red"])
    pid = make_photo(client, alice)
    url = f"/api/v1/photos/{pid}/renders"
    payload = {"spec_code": spec.code}

    result = client.post(url, json=payload, headers=alice)
    assert result.status_code == 200, result.text
    expected = result.json()
    assert expected["bg_color"] == "#438EDB"
    for color in (" Blue ", "#438edb"):
        result = client.post(url, json=payload | {"bg_color": color}, headers=alice)
        assert result.status_code == 200, result.text
        assert result.json()["id"] == expected["id"]

    spec.bg_colors = ["rebeccapurple"]
    db.flush()
    result = client.post(url, json=payload, headers=alice)
    assert (result.status_code, result.json()["code"]) == (422, "VALIDATION_ERROR")


def test_delete_removes_files_and_hides_photo(client, db, alice):
    make_spec(db, "ph_f")
    pid = make_photo(client, alice)
    client.post(f"/api/v1/photos/{pid}/renders", json={"spec_code": "ph_f"}, headers=alice)

    photo = db.get(Photo, pid)
    keys = [f.storage_key for f in db.scalars(select(File).where(File.user_id == photo.user_id))]
    assert len(keys) == 3
    assert all(get_storage().get(k) for k in keys)

    assert client.delete(f"/api/v1/photos/{pid}", headers=alice).json() == {"ok": True}

    assert client.get("/api/v1/photos", headers=alice).json()["items"] == []
    assert client.get(f"/api/v1/photos/{pid}", headers=alice).json()["code"] == "PHOTO_NOT_FOUND"
    for k in keys:
        with pytest.raises(FileNotFoundError):
            get_storage().get(k)
    db.expire_all()
    files = list(db.scalars(select(File).where(File.user_id == photo.user_id)))
    assert files and all(f.status == "purged" and f.purged_at for f in files)
    assert db.get(Photo, pid).status == "purged"


def test_purge_all_for_user(client, db, alice, bob):
    alice_photo = make_photo(client, alice)
    make_photo(client, alice)
    bob_photo = make_photo(client, bob)
    uid = db.get(Photo, bob_photo).user_id
    alice_uid = db.get(Photo, alice_photo).user_id

    n = photo_service.purge_all_for_user(db, alice_uid)
    assert n == 4
    assert client.get("/api/v1/photos", headers=alice).json()["items"] == []
    # 别人的不受影响
    assert len(client.get("/api/v1/photos", headers=bob).json()["items"]) == 1
    assert uid != alice_uid


def test_purge_orphan_uploads_only_removes_old_unreferenced_originals(client, db, alice):
    photo = db.get(Photo, make_photo(client, alice))
    attached = db.get(File, photo.original_file_id)
    matting = db.get(File, upload(client, alice).json()["file_id"])
    photo.matting_file_id = matting.id
    orphan = db.get(File, upload(client, alice).json()["file_id"])
    fresh = db.get(File, upload(client, alice).json()["file_id"])
    boundary = db.get(File, upload(client, alice).json()["file_id"])
    receipt = photo_service.save_file(
        db, user_id=photo.user_id, kind="receipt", data=b"receipt", mime="image/png", ext="png", owner="a1"
    )
    cutoff = utcnow() - timedelta(hours=24)
    for file in (attached, matting, orphan, receipt):
        file.created_at = cutoff - timedelta(seconds=1)
    boundary.created_at = cutoff
    db.flush()

    assert photo_service.purge_orphan_uploads(db, cutoff) == 1
    assert orphan.status == "purged" and orphan.purged_at is not None
    draft = db.scalar(select(Photo).where(Photo.original_file_id == orphan.id))
    assert draft.status == "purged"
    with pytest.raises(FileNotFoundError):
        get_storage().get(orphan.storage_key)
    for file in (attached, matting, fresh, boundary, receipt):
        assert file.status == "active" and file.purged_at is None
        assert get_storage().get(file.storage_key)
    assert photo_service.purge_orphan_uploads(db, cutoff) == 0
    r = client.post("/api/v1/photos", headers=alice, json={"file_id": orphan.id, "source": "upload"})
    assert r.json()["code"] == "UPLOAD_NOT_FOUND"
