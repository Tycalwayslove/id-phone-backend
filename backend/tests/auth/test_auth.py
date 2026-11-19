from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from tests.conftest import login

LOGIN = "/api/v1/auth/wechat-mini/login"


def test_login_new_user(client: TestClient):
    r = client.post(LOGIN, json={"code": "dev:alice"})
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    assert body["user"]["is_new"] is True
    assert body["user"]["phone_masked"] is None


def test_login_same_code_same_user(client: TestClient):
    a = client.post(LOGIN, json={"code": "dev:bob"}).json()
    b = client.post(LOGIN, json={"code": "dev:bob"}).json()
    assert a["user"]["id"] == b["user"]["id"]
    assert b["user"]["is_new"] is False
    assert a["token"] != b["token"]


def test_login_wechat_failed(client: TestClient):
    r = client.post(LOGIN, json={"code": "fail-xyz"})
    assert r.status_code == 400
    assert r.json()["code"] == "WECHAT_LOGIN_FAILED"


def test_login_disabled_account(client: TestClient, db: Session):
    uid = client.post(LOGIN, json={"code": "dev:carol"}).json()["user"]["id"]
    db.get(User, uid).status = "disabled"
    db.flush()
    r = client.post(LOGIN, json={"code": "dev:carol"})
    assert r.status_code == 403
    assert r.json()["code"] == "ACCOUNT_DISABLED"


def test_no_token_is_auth_required(client: TestClient):
    r = client.get("/api/v1/me")
    assert r.status_code == 401
    assert r.json()["code"] == "AUTH_REQUIRED"


def test_logout_invalidates_token(client: TestClient):
    h = login(client, "dev:dave")
    assert client.get("/api/v1/me", headers=h).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=h).json() == {"ok": True}
    r = client.get("/api/v1/me", headers=h)
    assert r.status_code == 401
    assert r.json()["code"] == "AUTH_INVALID"


def test_logout_keeps_other_session(client: TestClient):
    h1 = login(client, "dev:erin")
    h2 = login(client, "dev:erin")
    client.post("/api/v1/auth/logout", headers=h1)
    assert client.get("/api/v1/me", headers=h2).status_code == 200


def test_logout_requires_login(client: TestClient):
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 401
    assert r.json()["code"] == "AUTH_REQUIRED"
