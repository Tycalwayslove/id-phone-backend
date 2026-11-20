import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import get_db
from app.integrations import wechat
from app.main import app
from app.modules.photos import repo

CALLBACK = "/api/v1/callbacks/wechat/media-check"


def test_fake_media_check_does_not_use_wechat(monkeypatch):
    monkeypatch.setattr(settings, "media_check_mode", "fake")
    client = Mock()
    monkeypatch.setattr(wechat, "get_real_wechat", client)
    assert wechat.media_check_async(media_url="https://files.example.test/p.jpg", open_id=None) is None
    client.assert_not_called()


def test_real_media_check_reuses_mini_program_token(monkeypatch):
    monkeypatch.setattr(settings, "wechat_mode", "real")
    monkeypatch.setattr(settings, "media_check_mode", "real")
    monkeypatch.setattr(settings, "wx_mini_app_id", "test-app")
    monkeypatch.setattr(settings, "wx_mini_app_secret", "test-secret")
    monkeypatch.setattr(wechat, "_real", wechat.RealWechat())
    request = Mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "test-token", "expires_in": 7200}),
            httpx.Response(200, json={"errcode": 0, "trace_id": "trace-1"}),
            httpx.Response(200, json={"errcode": 0, "trace_id": "trace-2"}),
        ]
    )
    monkeypatch.setattr(wechat, "request_notification", request)
    media_url = "https://files.example.test/p.jpg"
    assert wechat.media_check_async(media_url=media_url, open_id="mini-user") == "trace-1"
    assert wechat.media_check_async(media_url=media_url, open_id="mini-user") == "trace-2"
    assert request.call_count == 3
    assert request.call_args_list[0].args == ("GET", "https://api.weixin.qq.com/cgi-bin/token")
    assert request.call_args.args == ("POST", "https://api.weixin.qq.com/wxa/media_check_async")
    assert request.call_args.kwargs == {
        "params": {"access_token": "test-token"},
        "json": {"media_url": media_url, "media_type": 2, "version": 2, "scene": 1, "openid": "mini-user"},
    }


@pytest.fixture
def callback(monkeypatch):
    monkeypatch.setattr(settings, "wx_msg_token", "test-message-token")
    monkeypatch.setattr(settings, "wx_mini_app_id", "test-app")
    timestamp, nonce = "1763452800", "98765"
    signed = "".join(sorted((settings.wx_msg_token, timestamp, nonce))).encode()
    params = {"timestamp": timestamp, "nonce": nonce, "signature": hashlib.sha1(signed).hexdigest()}
    db = Mock()
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: db)
    with TestClient(app) as client:
        yield client, params, db


def test_wechat_url_verification_requires_a_configured_valid_signature(callback, monkeypatch):
    client, params, _db = callback
    params = params | {"echostr": "123456789"}
    response = client.get(CALLBACK, params=params)
    assert response.status_code == 200 and response.text == "123456789"
    assert client.get(CALLBACK, params=params | {"signature": "a" * 40}).status_code == 401
    monkeypatch.setattr(settings, "wx_msg_token", "")
    assert client.get(CALLBACK, params=params).status_code == 401


@pytest.mark.parametrize(
    ("suggest", "expected"), [("pass", "passed"), ("risky", "rejected"), ("review", "rejected")]
)
def test_wechat_post_checks_signature_and_persists_verdict(callback, monkeypatch, suggest, expected):
    client, params, db = callback
    photo = SimpleNamespace(status="draft", check_result={"status": "pending", "trace_id": "trace-1"})
    lookup = Mock(return_value=photo)
    monkeypatch.setattr(repo, "lock_photo_for_media_check", lookup)
    event = {
        "MsgType": "event",
        "Event": "wxa_media_check",
        "appid": "test-app",
        "trace_id": "trace-1",
        "errcode": 0,
        "result": {"suggest": suggest},
    }
    assert client.post(CALLBACK, params=params | {"signature": "a" * 40}, json=event).status_code == 401
    assert client.post(CALLBACK, params=params, json=event | {"appid": "another-app"}).status_code == 422
    lookup.assert_not_called()
    response = client.post(CALLBACK, params=params, json=event)
    assert response.status_code == 200 and response.text == "success"
    lookup.assert_called_once_with(db, "trace-1")
    db.commit.assert_called_once_with()
    assert photo.check_result == {"status": expected, "trace_id": "trace-1"}


def test_real_login_with_fake_media_check_skips_wechat(monkeypatch):
    """本机开发：WECHAT_MODE=real 登录，MEDIA_CHECK_MODE=fake 不调用微信内容检测。"""
    monkeypatch.setattr(settings, "wechat_mode", "real")
    monkeypatch.setattr(settings, "media_check_mode", "fake")
    client = Mock()
    monkeypatch.setattr(wechat, "get_real_wechat", client)
    assert wechat.media_check_async(media_url="https://files.example.test/p.jpg", open_id="o-test") is None
    client.assert_not_called()
