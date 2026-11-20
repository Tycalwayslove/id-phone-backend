"""微信服务端接口：小程序登录、换手机号、发送订阅与模板消息。

fake 模式（默认）不访问微信，规则：
- code 以 "dev:" 开头：openid 取冒号后面的内容，如 "dev:alice" → openid "alice"，方便联调时固定身份
- code 以 "fail" 开头：模拟微信返回错误
- 其他：按 code 生成一个稳定的假 openid
- 手机号 code 形如 "phone:13800001234" 时返回这个号码，否则按 code 生成一个 138 开头的假号码
"""

import hashlib
import logging
import threading
from dataclasses import dataclass
from time import monotonic
from typing import Literal, Protocol

import httpx

from app.core.config import settings
from app.core.errors import AppError, ErrorCode


@dataclass
class WechatSession:
    app_id: str
    open_id: str
    union_id: str | None


class WechatMiniClient(Protocol):
    def code2session(self, code: str) -> WechatSession: ...
    def get_phone_number(self, code: str) -> str: ...


class FakeWechat:
    def code2session(self, code: str) -> WechatSession:
        if code.startswith("fail"):
            raise AppError(ErrorCode.WECHAT_LOGIN_FAILED)
        if code.startswith("dev:"):
            open_id = code[4:] or "dev"
        else:
            open_id = "fake_" + hashlib.sha256(code.encode()).hexdigest()[:16]
        return WechatSession(app_id=settings.wx_mini_app_id, open_id=open_id, union_id=f"union_{open_id}")

    def get_phone_number(self, code: str) -> str:
        if code.startswith("fail"):
            raise AppError(ErrorCode.WECHAT_LOGIN_FAILED, "获取手机号失败")
        if code.startswith("phone:"):
            return code[6:]
        return "138" + str(int(hashlib.sha256(code.encode()).hexdigest(), 16))[:8]


class DeliveryError(Exception):
    """通知失败原因使用固定值，供任务记录和升级判断使用。"""

    def __init__(self, reason: str, outcome: Literal["retry", "failed", "skipped"] = "retry") -> None:
        super().__init__(reason)
        self.reason = reason
        self.outcome = outcome


class _SensitiveQueryFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # httpx 的 INFO 请求日志包含完整 URL。微信凭据和短信手机号由上游规定放在查询串。
        args = record.args
        if (
            isinstance(args, tuple)
            and len(args) == 5
            and isinstance(record.msg, str)
            and record.msg.startswith("HTTP Request:")
        ):
            url = args[1]
            if isinstance(url, httpx.URL) and url.host in ("api.weixin.qq.com", "dysmsapi.aliyuncs.com"):
                record.args = (args[0], url.copy_with(query=None), args[2], args[3], "")
        return True


logging.getLogger("httpx").addFilter(_SensitiveQueryFilter())

_WECHAT_BASE = "https://api.weixin.qq.com"


def request_notification(method: str, url: str, **kwargs) -> httpx.Response:
    try:
        response = httpx.request(method, url, timeout=5, follow_redirects=False, **kwargs)
    except httpx.RequestError:
        raise DeliveryError("network_error") from None
    if response.status_code in (408, 425, 429) or response.status_code >= 500:
        raise DeliveryError("upstream_unavailable")
    return response


def notification_json(response: httpx.Response, *, error_statuses: tuple[int, ...] = ()) -> dict:
    if not response.is_success and response.status_code not in error_statuses:
        raise DeliveryError("http_rejected", "failed")
    try:
        data = response.json()
    except ValueError:
        raise DeliveryError("invalid_response") from None
    if not isinstance(data, dict):
        raise DeliveryError("invalid_response")
    return data


class _WechatAccessToken:
    def __init__(self) -> None:
        self._token: str | None = None
        self._refresh_at = 0.0
        self._credentials: tuple[str, str] | None = None
        self._lock = threading.Lock()

    def get(self, app_id: str, app_secret: str) -> str:
        if not app_id or not app_secret:
            raise DeliveryError("channel_not_configured", "failed")
        with self._lock:
            now = monotonic()
            credentials = (app_id, app_secret)
            if self._token and self._credentials == credentials and now < self._refresh_at:
                return self._token
            data = notification_json(
                request_notification(
                    "GET",
                    f"{_WECHAT_BASE}/cgi-bin/token",
                    params={"grant_type": "client_credential", "appid": app_id, "secret": app_secret},
                )
            )
            token = data.get("access_token")
            if not isinstance(token, str) or not token:
                outcome = "failed" if data.get("errcode") in (40001, 40013, 40125) else "retry"
                raise DeliveryError("token_unavailable", outcome)
            try:
                expires_in = int(data.get("expires_in", 7200))
            except TypeError, ValueError, OverflowError:
                raise DeliveryError("invalid_response") from None
            if expires_in <= 0:
                raise DeliveryError("invalid_response")
            self._credentials = credentials
            self._token = token
            self._refresh_at = now + expires_in - min(300, expires_in / 10)
            return token

    def invalidate(self, token: str) -> None:
        with self._lock:
            if self._token == token:
                self._token = None


def _send_wechat_message(
    path: str,
    payload: dict,
    *,
    token: str,
    cache: _WechatAccessToken,
    unreachable: dict[int, str],
) -> None:
    data = notification_json(
        request_notification("POST", f"{_WECHAT_BASE}{path}", params={"access_token": token}, json=payload)
    )
    code = data.get("errcode")
    if type(code) is not int:
        raise DeliveryError("invalid_response")
    if code in unreachable:
        raise DeliveryError(unreachable[code], "skipped")
    if code in (40001, 40014, 42001):
        cache.invalidate(token)
        raise DeliveryError("token_rejected")
    if code != 0:
        raise DeliveryError("provider_rejected")


class RealWechat:
    def __init__(self) -> None:
        self._token_cache = _WechatAccessToken()

    def code2session(self, code: str) -> WechatSession:
        r = httpx.get(
            f"{_WECHAT_BASE}/sns/jscode2session",
            params={
                "appid": settings.wx_mini_app_id,
                "secret": settings.wx_mini_app_secret,
                "js_code": code,
                "grant_type": "authorization_code",
            },
            timeout=5,
        )
        data = r.json()
        if data.get("errcode") or not data.get("openid"):
            raise AppError(ErrorCode.WECHAT_LOGIN_FAILED)
        # session_key 只在需要解密微信加密数据时用，这里不保存、不下发
        return WechatSession(
            app_id=settings.wx_mini_app_id, open_id=data["openid"], union_id=data.get("unionid")
        )

    def _access_token(self) -> str:
        return self._token_cache.get(settings.wx_mini_app_id, settings.wx_mini_app_secret)

    def get_phone_number(self, code: str) -> str:
        try:
            token = self._access_token()
        except DeliveryError:
            raise AppError(ErrorCode.WECHAT_LOGIN_FAILED, "微信接口凭证获取失败") from None
        r = httpx.post(
            f"{_WECHAT_BASE}/wxa/business/getuserphonenumber",
            params={"access_token": token},
            json={"code": code},
            timeout=5,
        )
        data = r.json()
        phone = (data.get("phone_info") or {}).get("purePhoneNumber")
        if data.get("errcode") or not phone:
            raise AppError(ErrorCode.WECHAT_LOGIN_FAILED, "获取手机号失败")
        return phone

    def send_subscribe_message(
        self,
        *,
        open_id: str,
        template_id: str,
        data: dict[str, dict[str, str]],
        page: str | None = None,
    ) -> None:
        """调用小程序 subscribeMessage.send，复用小程序接口的凭证。"""
        payload = {
            "touser": open_id,
            "template_id": template_id,
            "data": data,
            "miniprogram_state": "formal",
            "lang": "zh_CN",
        }
        if page:
            payload["page"] = page
        _send_wechat_message(
            "/cgi-bin/message/subscribe/send",
            payload,
            token=self._access_token(),
            cache=self._token_cache,
            unreachable={40003: "invalid_mini_recipient", 43101: "subscription_unavailable"},
        )


_mp_token = _WechatAccessToken()


def send_mp_template_message(*, open_id: str, template_id: str, data: dict[str, dict[str, str]]) -> None:
    _send_wechat_message(
        "/cgi-bin/message/template/send",
        {"touser": open_id, "template_id": template_id, "data": data},
        token=_mp_token.get(settings.wx_mp_app_id, settings.wx_mp_app_secret),
        cache=_mp_token,
        unreachable={40003: "invalid_mp_recipient", 43004: "not_following_mp"},
    )


_fake = FakeWechat()
_real = RealWechat()


def get_real_wechat() -> RealWechat:
    return _real


def get_wechat() -> WechatMiniClient:
    return _fake if settings.wechat_mode == "fake" else get_real_wechat()
