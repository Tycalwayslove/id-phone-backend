"""通知通道适配器。服务商响应仅转换为固定的结果，不存储原始响应。"""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote, urlencode
from uuid import uuid4

from app.core.config import settings
from app.integrations.wechat import (
    DeliveryError,
    get_real_wechat,
    notification_json,
    request_notification,
    send_mp_template_message,
)

MINI_SUBSCRIBE = "mini_subscribe"
MP_TEMPLATE = "mp_template"
WECOM = "wecom"
SMS = "sms"
CHANNEL_ORDER = (MINI_SUBSCRIBE, MP_TEMPLATE, WECOM, SMS)


@dataclass(frozen=True)
class Notification:
    recipient: str = field(repr=False)
    event: str
    step: int
    delivery_id: str


class NotifyChannel(Protocol):
    def send(self, message: Notification) -> None: ...


class FakeChannel:
    """模拟服务商接收成功，调用方仍要检查用户是否可达。"""

    def send(self, message: Notification) -> None:
        pass


def get_template(channel: str, event: str) -> dict:
    templates = {
        MINI_SUBSCRIBE: settings.mini_subscribe_templates,
        MP_TEMPLATE: settings.mp_template_templates,
        SMS: settings.sms_templates,
    }
    return templates[channel].get(event, {})


def _wechat_template(channel: str, event: str) -> tuple[str, dict[str, dict[str, str]]]:
    template = get_template(channel, event)
    template_id, fields = template.get("template_id"), template.get("data")
    if not template_id:
        raise DeliveryError("no_template", "skipped")
    if not isinstance(fields, dict) or not fields:
        raise DeliveryError("invalid_template", "failed")
    return template_id, {name: {"value": value} for name, value in fields.items()}


class MiniSubscribe:
    def send(self, message: Notification) -> None:
        template_id, data = _wechat_template(MINI_SUBSCRIBE, message.event)
        get_real_wechat().send_subscribe_message(
            open_id=message.recipient,
            template_id=template_id,
            data=data,
            page=get_template(MINI_SUBSCRIBE, message.event).get("page"),
        )


class MpTemplate:
    def send(self, message: Notification) -> None:
        template_id, data = _wechat_template(MP_TEMPLATE, message.event)
        send_mp_template_message(open_id=message.recipient, template_id=template_id, data=data)


class Wecom:
    def send(self, message: Notification) -> None:
        # 企业微信给外部联系人主动发消息需要员工确认，worker 无法确认实际发送。
        raise DeliveryError("wecom_requires_confirmation", "skipped")


class AliyunSms:
    _HOST = "dysmsapi.aliyuncs.com"
    _ALGORITHM = "ACS3-HMAC-SHA256"

    def __init__(self, *, access_key_id: str, access_key_secret: str, sign_name: str) -> None:
        self._access_key_id = access_key_id
        self._access_key_secret = access_key_secret
        self._sign_name = sign_name

    def _headers(self, query: str) -> dict[str, str]:
        # SendSms 参数在查询串中，POST 的请求体为空。
        payload_hash = hashlib.sha256(b"").hexdigest()
        headers = {
            "host": self._HOST,
            "x-acs-action": "SendSms",
            "x-acs-content-sha256": payload_hash,
            "x-acs-date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "x-acs-signature-nonce": str(uuid4()),
            "x-acs-version": "2017-05-25",
        }
        ordered_names = sorted(headers)
        signed_headers = ";".join(ordered_names)
        canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in ordered_names)
        canonical = "\n".join(("POST", "/", query, canonical_headers, signed_headers, payload_hash))
        to_sign = f"{self._ALGORITHM}\n{hashlib.sha256(canonical.encode()).hexdigest()}"
        signature = hmac.digest(self._access_key_secret.encode(), to_sign.encode(), "sha256").hex()
        headers["Authorization"] = (
            f"{self._ALGORITHM} Credential={self._access_key_id},"
            f"SignedHeaders={signed_headers},Signature={signature}"
        )
        return headers

    def send(self, message: Notification) -> None:
        template = get_template(SMS, message.event)
        template_code = template.get("template_code")
        if not template_code:
            raise DeliveryError("no_template", "skipped")
        phone = message.recipient
        if not re.fullmatch(r"(?:1[0-9]{10}|\+[1-9][0-9]{6,14})", phone):
            raise DeliveryError("invalid_phone", "skipped")
        params = {
            "PhoneNumbers": phone,
            "SignName": self._sign_name,
            "TemplateCode": template_code,
            "OutId": message.delivery_id,
        }
        template_params = template.get("params", {})
        if not isinstance(template_params, dict):
            raise DeliveryError("invalid_template", "failed")
        if template_params:
            params["TemplateParam"] = json.dumps(
                template_params, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
        query = urlencode(sorted(params.items()), quote_via=quote)
        response = request_notification(
            "POST", f"https://{self._HOST}/?{query}", headers=self._headers(query)
        )
        code = notification_json(response, error_statuses=(400, 403)).get("Code")
        if code == "OK" and response.is_success:
            return
        if code == "isv.MOBILE_NUMBER_ILLEGAL":
            raise DeliveryError("invalid_phone", "skipped")
        if code == "isv.BLACK_KEY_CONTROL_LIMIT":
            raise DeliveryError("phone_blacklisted", "skipped")
        if not isinstance(code, str) or code == "OK":
            raise DeliveryError("invalid_response")
        raise DeliveryError("provider_rejected")


def get_channel(channel: str, mode: str) -> NotifyChannel:
    if channel not in CHANNEL_ORDER:
        raise DeliveryError("invalid_channel", "failed")
    if mode == "fake":
        return FakeChannel()
    if mode != "real":
        raise DeliveryError("invalid_channel_mode", "failed")
    if channel == MINI_SUBSCRIBE:
        return MiniSubscribe()
    if channel == MP_TEMPLATE:
        return MpTemplate()
    if channel == WECOM:
        return Wecom()
    if not all((settings.sms_access_key_id, settings.sms_access_key_secret, settings.sms_sign_name)):
        raise DeliveryError("channel_not_configured", "failed")
    return AliyunSms(
        access_key_id=settings.sms_access_key_id,
        access_key_secret=settings.sms_access_key_secret,
        sign_name=settings.sms_sign_name,
    )
