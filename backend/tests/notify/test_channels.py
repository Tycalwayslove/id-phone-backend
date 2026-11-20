import json
import logging
from datetime import UTC, datetime
from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations import notify_channels as channels
from app.integrations import wechat
from app.integrations.wechat import DeliveryError
from app.models import NotifyTask, UserIdentity
from app.modules.notify import repo, service
from app.modules.users import service as users_service

WECHAT_CASES = [
    (
        channels.MINI_SUBSCRIBE,
        "mini",
        "/cgi-bin/message/subscribe/send",
        {
            "touser": "fake-openid",
            "template_id": "template-1",
            "data": {"thing1": {"value": "办理成功"}},
            "miniprogram_state": "formal",
            "lang": "zh_CN",
            "page": "pages/receipts/index",
        },
        43101,
        "subscription_unavailable",
    ),
    (
        channels.MP_TEMPLATE,
        "mp",
        "/cgi-bin/message/template/send",
        {
            "touser": "fake-openid",
            "template_id": "template-1",
            "data": {"thing1": {"value": "办理成功"}},
        },
        43004,
        "not_following_mp",
    ),
]


@pytest.fixture
def channel_settings(monkeypatch):
    template = {
        "receipt_completed": {
            "template_id": "template-1",
            "data": {"thing1": "办理成功"},
            "page": "pages/receipts/index",
        }
    }
    settings = {
        "mini_subscribe_templates": template,
        "mp_template_templates": template,
        "sms_templates": {
            "receipt_completed": {"template_code": "SMS_1001", "params": {"status": "办理 成功"}}
        },
        "wx_mini_app_id": "fake-mini-app",
        "wx_mini_app_secret": "fake-mini-secret",
        "wx_mp_app_id": "fake-mp-app",
        "wx_mp_app_secret": "fake-mp-secret",
        "sms_access_key_id": "fake-access-key-id",
        "sms_access_key_secret": "fake-access-key-secret",
        "sms_sign_name": "证件照",
    }
    for name, value in settings.items():
        monkeypatch.setattr(channels.settings, name, value)
    monkeypatch.setattr(wechat, "_real", wechat.RealWechat())
    monkeypatch.setattr(wechat, "_mp_token", wechat._WechatAccessToken())


def test_loads_notification_config_from_environment(monkeypatch):
    monkeypatch.setenv("NOTIFY_CHANNELS", "mini_subscribe,mp_template,wecom,sms")
    monkeypatch.setenv("SMS_MODE", "real")
    monkeypatch.setenv("SMS_TEMPLATES", '{"receipt_completed":{"template_code":"SMS_1001"}}')
    loaded = Settings(_env_file=None, database_url="postgresql+psycopg://x@localhost/x")
    assert loaded.notify_channels == "mini_subscribe,mp_template,wecom,sms"
    assert loaded.sms_mode == "real"
    assert loaded.sms_templates["receipt_completed"]["template_code"] == "SMS_1001"


@pytest.mark.parametrize("channel", channels.CHANNEL_ORDER)
def test_fake_channel_makes_no_http_call(channel, monkeypatch):
    def unexpected_request(*args, **kwargs):
        pytest.fail("fake 模式不应访问服务商")

    monkeypatch.setattr(httpx, "request", unexpected_request)
    channels.get_channel(channel, "fake").send(
        channels.Notification("fake-openid", "receipt_completed", 1, "job")
    )


@pytest.mark.parametrize(("channel", "account", "path", "body", "errcode", "reason"), WECHAT_CASES)
def test_wechat_send_and_unreachable(
    channel, account, path, body, errcode, reason, channel_settings, monkeypatch, caplog
):
    caplog.set_level(logging.DEBUG)
    result_codes = iter((0, errcode))
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.weixin.qq.com"
        calls.append(request.url.path)
        if request.url.path == "/cgi-bin/token":
            assert request.method == "GET"
            assert dict(request.url.params) == {
                "grant_type": "client_credential",
                "appid": f"fake-{account}-app",
                "secret": f"fake-{account}-secret",
            }
            return httpx.Response(200, json={"access_token": f"fake-{account}-token", "expires_in": 7200})
        assert request.method == "POST"
        assert request.url.path == path
        assert dict(request.url.params) == {"access_token": f"fake-{account}-token"}
        assert json.loads(request.content) == body
        return httpx.Response(200, json={"errcode": next(result_codes), "errmsg": "private data"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(httpx, "request", client.request)
        adapter = channels.get_channel(channel, "real")
        message = channels.Notification("fake-openid", "receipt_completed", 1, "job")
        adapter.send(message)
        with pytest.raises(DeliveryError, match=reason) as exc:
            adapter.send(message)

    assert exc.value.outcome == "skipped"
    assert calls == ["/cgi-bin/token", path, path]
    assert path in caplog.text
    for sensitive in (
        "access_token=",
        "secret=",
        f"fake-{account}-token",
        f"fake-{account}-secret",
        "fake-openid",
        "private data",
    ):
        assert sensitive not in caplog.text


def test_mp_refreshes_before_expiry_and_rejected_token_is_invalidated(channel_settings, monkeypatch):
    now = 1000
    monkeypatch.setattr(wechat, "monotonic", lambda: now)
    tokens = iter(("fake-mp-token-1", "fake-mp-token-2", "fake-mp-token-3"))
    accepted_tokens = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(200, json={"access_token": next(tokens), "expires_in": 7200})
        token = request.url.params["access_token"]
        accepted_tokens.append(token)
        if token == "fake-mp-token-2":
            return httpx.Response(200, json={"errcode": 42001})
        return httpx.Response(200, json={"errcode": 0})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(httpx, "request", client.request)
        adapter = channels.get_channel(channels.MP_TEMPLATE, "real")
        message = channels.Notification("fake-openid", "receipt_completed", 1, "job")
        adapter.send(message)
        now += 6899
        adapter.send(message)
        now += 1
        with pytest.raises(DeliveryError, match=r"^token_rejected$"):
            channels.get_channel(channels.MP_TEMPLATE, "real").send(message)
        adapter.send(message)

    assert accepted_tokens == ["fake-mp-token-1", "fake-mp-token-1", "fake-mp-token-2", "fake-mp-token-3"]


def test_mini_phone_and_notifications_share_access_token(channel_settings, monkeypatch):
    monkeypatch.setattr(channels.settings, "wechat_mode", "real")
    paths = []

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        paths.append(path)
        if path == "/cgi-bin/token":
            return httpx.Response(200, json={"access_token": "fake-mini-token"})
        assert request.url.params["access_token"] == "fake-mini-token"
        if path == "/wxa/business/getuserphonenumber":
            return httpx.Response(200, json={"errcode": 0, "phone_info": {"purePhoneNumber": "13800000000"}})
        return httpx.Response(200, json={"errcode": 0})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(httpx, "request", client.request)
        monkeypatch.setattr(httpx, "post", client.post)
        assert wechat.get_wechat().get_phone_number("fake-code") == "13800000000"
        channels.get_channel(channels.MINI_SUBSCRIBE, "real").send(
            channels.Notification("fake-openid", "receipt_completed", 1, "job")
        )
    assert paths == ["/cgi-bin/token", "/wxa/business/getuserphonenumber", "/cgi-bin/message/subscribe/send"]


def test_real_wechat_refusal_escalates_through_missing_mp_and_real_wecom(channel_settings, monkeypatch):
    db = Mock(spec=Session)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    root = NotifyTask(
        id=1,
        user_id=2,
        application_id=3,
        event="receipt_completed",
        channel="mini_subscribe",
        step=1,
        scheduled_at=now,
        status="pending",
    )
    tasks = [root]
    identity = UserIdentity(open_id="fake-mini-openid", subscribe_quota={"template-1": 1})
    mp_identity = Mock(return_value=None)
    get_phone = Mock(return_value="13800000000")
    monkeypatch.setattr(users_service, "is_active_user", Mock(return_value=True))
    monkeypatch.setattr(users_service, "get_notification_phone", get_phone)
    monkeypatch.setattr(repo, "get_mini_identity", Mock(return_value=identity))
    monkeypatch.setattr(repo, "get_mp_open_id", mp_identity)
    wecom_recipient = Mock()
    monkeypatch.setattr(repo, "get_wecom_recipient", wecom_recipient)
    monkeypatch.setattr(service, "utcnow", lambda: now)
    monkeypatch.setattr(channels.settings, "notify_channels", ",".join(channels.CHANNEL_ORDER))
    for mode in ("mini_subscribe_mode", "mp_template_mode", "wecom_mode"):
        monkeypatch.setattr(channels.settings, mode, "real")
    monkeypatch.setattr(channels.settings, "sms_mode", "fake")

    def next_due(_db, cutoff, excluded_ids):
        return next(
            (task for task in tasks if task.status == "pending" and task.id not in excluded_ids), None
        )

    def enqueue(_db, *, generation, **fields):
        tasks.append(NotifyTask(id=len(tasks) + 1, status="pending", **fields))
        return True

    paths = []

    def handle(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/cgi-bin/token":
            assert request.url.params["appid"] == channels.settings.wx_mini_app_id
            return httpx.Response(200, json={"access_token": "fake-mini-token"})
        assert request.url.path == "/cgi-bin/message/subscribe/send"
        return httpx.Response(200, json={"errcode": 43101, "errmsg": "user refused"})

    monkeypatch.setattr(repo, "next_due_task", next_due)
    monkeypatch.setattr(repo, "insert_task_once", enqueue)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(httpx, "request", client.request)
        assert service.send_due(db) == 4
        assert service.send_due(db) == 0

    assert [(task.channel, task.status, task.result.get("reason")) for task in tasks] == [
        ("mini_subscribe", "skipped", "subscription_unavailable"),
        ("mp_template", "skipped", "no_mp_identity"),
        ("wecom", "skipped", "wecom_requires_confirmation"),
        ("sms", "sent", None),
    ]
    assert {(task.application_id, task.event, task.step) for task in tasks} == {(3, "receipt_completed", 1)}
    assert identity.subscribe_quota == {"template-1": 0}
    assert paths == ["/cgi-bin/token", "/cgi-bin/message/subscribe/send"]
    mp_identity.assert_called_once_with(db, 2, app_id=channels.settings.wx_mp_app_id)
    wecom_recipient.assert_not_called()
    get_phone.assert_called_once_with(db, 2)


def test_wechat_transport_failure_is_sanitized(monkeypatch, channel_settings, caplog):
    secret = "fake-private-upstream-body"

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(200, json={"access_token": "fake-mini-token"})
        raise httpx.ReadTimeout(secret, request=request)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(httpx, "request", client.request)
        adapter = channels.get_channel(channels.MINI_SUBSCRIBE, "real")
        with pytest.raises(DeliveryError, match=r"^network_error$") as exc:
            adapter.send(channels.Notification("fake-openid", "receipt_completed", 1, "job"))
    assert exc.value.outcome == "retry"
    assert secret not in caplog.text


@pytest.mark.parametrize("errcode", [None, False, "0", -1])
def test_wechat_ambiguous_response_is_not_success(errcode, channel_settings, monkeypatch):
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(200, json={"access_token": "fake-mini-token"})
        return httpx.Response(200, json={"errcode": errcode})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(httpx, "request", client.request)
        adapter = channels.get_channel(channels.MINI_SUBSCRIBE, "real")
        with pytest.raises(DeliveryError) as exc:
            adapter.send(channels.Notification("fake-openid", "receipt_completed", 1, "job"))
    assert exc.value.outcome == "retry"


def test_sms_signed_send_and_provider_failure(monkeypatch, channel_settings, caplog):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 1, tzinfo=UTC)

    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(channels, "datetime", FixedDateTime)
    monkeypatch.setattr(channels, "uuid4", lambda: "64d8b6d1-c6ba-4ef6-90e6-4abfde99607f")
    responses = iter(((200, "OK"), (400, "isv.BUSINESS_LIMIT_CONTROL"), (400, "isv.MOBILE_NUMBER_ILLEGAL")))

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.copy_with(query=None) == "https://dysmsapi.aliyuncs.com/"
        assert request.headers["x-acs-action"] == "SendSms"
        assert request.headers["x-acs-version"] == "2017-05-25"
        assert request.headers["x-acs-date"] == "2026-01-01T00:00:00Z"
        assert request.headers["x-acs-content-sha256"] == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
        assert request.headers["Authorization"] == (
            "ACS3-HMAC-SHA256 Credential=fake-access-key-id,"
            "SignedHeaders=host;x-acs-action;x-acs-content-sha256;x-acs-date;x-acs-signature-nonce;x-acs-version,"
            "Signature=d8f65e0a157b3444bf10f8c4261b01ead751ed476773fe840308d4a64ca1c423"
        )
        assert request.content == b""
        assert b"PhoneNumbers=%2B8613800000000" in request.url.query
        assert b"%20" in request.url.query
        assert dict(request.url.params) == {
            "PhoneNumbers": "+8613800000000",
            "SignName": "证件照",
            "TemplateCode": "SMS_1001",
            "TemplateParam": '{"status":"办理 成功"}',
            "OutId": "job",
        }
        status, code = next(responses)
        return httpx.Response(status, json={"Code": code, "Message": "private provider data"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(httpx, "request", client.request)
        adapter = channels.get_channel(channels.SMS, "real")
        message = channels.Notification("+8613800000000", "receipt_completed", 1, "job")
        adapter.send(message)
        with pytest.raises(DeliveryError, match=r"^provider_rejected$") as rejected:
            adapter.send(message)
        with pytest.raises(DeliveryError, match=r"^invalid_phone$") as invalid_phone:
            adapter.send(message)
    assert rejected.value.outcome == "retry"
    assert invalid_phone.value.outcome == "skipped"
    assert "dysmsapi.aliyuncs.com" in caplog.text
    for sensitive in ("13800000000", "PhoneNumbers=", "fake-access-key", "private provider data"):
        assert sensitive not in caplog.text
