import io
from urllib.parse import urlparse

import pytest
from PIL import Image
from sqlalchemy import select

from app.integrations.storage import get_storage
from app.models import File, Photo
from app.modules.photos import service as photo_service
from tests.conftest import login
from tests.factories import make_spec
from tests.photos.helpers import jpeg_bytes, make_photo, set_access, upload


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


def test_upload_create_list(client, alice):
    r = upload(client, alice)
    assert r.status_code == 200
    up = r.json()
    assert (up["width"], up["height"]) == (600, 800)

    r = client.post("/api/v1/photos", json={"file_id": up["file_id"], "source": "camera"}, headers=alice)
    assert r.status_code == 200, r.text
    photo = r.json()
    assert photo["source"] == "camera" and photo["status"] == "active"
    assert photo["access"]["active"] is False

    items = client.get("/api/v1/photos", headers=alice).json()["items"]
    assert [i["id"] for i in items] == [photo["id"]]
    assert "renders" not in items[0]

    # 同一个文件不能再创建第二张照片
    r = client.post("/api/v1/photos", json={"file_id": up["file_id"], "source": "camera"}, headers=alice)
    assert r.json()["code"] == "UPLOAD_NOT_FOUND"


def test_list_pagination_newest_first(client, alice):
    ids = [make_photo(client, alice) for _ in range(3)]
    p1 = client.get("/api/v1/photos", params={"limit": 2}, headers=alice).json()
    assert [i["id"] for i in p1["items"]] == [ids[2], ids[1]]
    p2 = client.get("/api/v1/photos", params={"limit": 2, "cursor": p1["next_cursor"]}, headers=alice).json()
    assert [i["id"] for i in p2["items"]] == [ids[0]]
    assert p2["next_cursor"] is None


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


def test_delete_removes_files_and_hides_photo(client, db, alice):
    make_spec(db, "ph_f")
    pid = make_photo(client, alice)
    client.post(f"/api/v1/photos/{pid}/renders", json={"spec_code": "ph_f"}, headers=alice)

    photo = db.get(Photo, pid)
    keys = [f.storage_key for f in db.scalars(select(File).where(File.user_id == photo.user_id))]
    assert len(keys) == 2
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
    assert n == 2
    assert client.get("/api/v1/photos", headers=alice).json()["items"] == []
    # 别人的不受影响
    assert len(client.get("/api/v1/photos", headers=bob).json()["items"]) == 1
    assert uid != alice_uid
