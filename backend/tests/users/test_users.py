from fastapi.testclient import TestClient

from tests.conftest import login

ME = "/api/v1/me"


def test_get_me(client: TestClient):
    h = login(client, "dev:alice")
    r = client.get(ME, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["has_phone"] is False
    assert body["phone_masked"] is None
    assert body["created_at"]


def test_update_nickname_only_changes_given_fields(client: TestClient):
    h = login(client, "dev:alice")
    r = client.patch(ME, headers=h, json={"nickname": "小明"})
    assert r.status_code == 200
    assert r.json()["nickname"] == "小明"
    r = client.patch(ME, headers=h, json={"avatar_url": "https://example.com/a.png"})
    assert r.json()["nickname"] == "小明"
    assert r.json()["avatar_url"] == "https://example.com/a.png"


def test_update_validation(client: TestClient):
    h = login(client, "dev:alice")
    assert client.patch(ME, headers=h, json={"nickname": ""}).status_code == 422
    assert client.patch(ME, headers=h, json={"nickname": "x" * 33}).status_code == 422
    r = client.patch(ME, headers=h, json={"avatar_url": "http://example.com/a.png"})
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_bind_phone(client: TestClient):
    h = login(client, "dev:alice")
    r = client.post(f"{ME}/phone", headers=h, json={"code": "phone:13800001234"})
    assert r.status_code == 200
    assert r.json()["phone_masked"] == "138****1234"
    assert r.json()["has_phone"] is True
    assert client.get(ME, headers=h).json()["phone_masked"] == "138****1234"


def test_bind_same_phone_twice_by_same_user_ok(client: TestClient):
    h = login(client, "dev:alice")
    for _ in range(2):
        r = client.post(f"{ME}/phone", headers=h, json={"code": "phone:13800001234"})
        assert r.status_code == 200


def test_bind_phone_already_bound_by_other_user(client: TestClient):
    h1 = login(client, "dev:alice")
    h2 = login(client, "dev:bob")
    assert client.post(f"{ME}/phone", headers=h1, json={"code": "phone:13800001234"}).status_code == 200
    r = client.post(f"{ME}/phone", headers=h2, json={"code": "phone:13800001234"})
    assert r.status_code == 409
    assert r.json()["code"] == "PHONE_ALREADY_BOUND"


def test_cancel_requires_confirm(client: TestClient):
    h = login(client, "dev:alice")
    r = client.post(f"{ME}/cancel", headers=h, json={"confirm": False})
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"
    assert client.get(ME, headers=h).status_code == 200


def test_cancel_invalidates_token_and_relogin_is_new_user(client: TestClient):
    first = client.post("/api/v1/auth/wechat-mini/login", json={"code": "dev:zoe"}).json()
    h = {"Authorization": f"Bearer {first['token']}"}
    client.post(f"{ME}/phone", headers=h, json={"code": "phone:13800005678"})
    client.patch(ME, headers=h, json={"nickname": "旧昵称"})

    assert client.post(f"{ME}/cancel", headers=h, json={"confirm": True}).json() == {"ok": True}
    r = client.get(ME, headers=h)
    assert r.status_code == 401
    assert r.json()["code"] == "AUTH_INVALID"

    second = client.post("/api/v1/auth/wechat-mini/login", json={"code": "dev:zoe"}).json()
    assert second["user"]["is_new"] is True
    assert second["user"]["id"] != first["user"]["id"]
    assert second["user"]["nickname"] is None
    assert second["user"]["phone_masked"] is None

    # 注销后手机号释放，可被新账号绑定
    h2 = {"Authorization": f"Bearer {second['token']}"}
    r = client.post(f"{ME}/phone", headers=h2, json={"code": "phone:13800005678"})
    assert r.status_code == 200
