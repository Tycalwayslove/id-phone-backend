"""微信小程序服务端接口：登录换 openid、换手机号。

fake 模式（默认）不访问微信，规则：
- code 以 "dev:" 开头：openid 取冒号后面的内容，如 "dev:alice" → openid "alice"，方便联调时固定身份
- code 以 "fail" 开头：模拟微信返回错误
- 其他：按 code 生成一个稳定的假 openid
- 手机号 code 形如 "phone:13800001234" 时返回这个号码，否则按 code 生成一个 138 开头的假号码
"""

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Protocol

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


class RealWechat:
    _BASE = "https://api.weixin.qq.com"

    def __init__(self) -> None:
        self._token: str | None = None
        self._token_expire = 0.0
        self._lock = threading.Lock()

    def code2session(self, code: str) -> WechatSession:
        r = httpx.get(
            f"{self._BASE}/sns/jscode2session",
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
        with self._lock:
            if self._token and time.time() < self._token_expire - 300:
                return self._token
            r = httpx.get(
                f"{self._BASE}/cgi-bin/token",
                params={
                    "grant_type": "client_credential",
                    "appid": settings.wx_mini_app_id,
                    "secret": settings.wx_mini_app_secret,
                },
                timeout=5,
            )
            data = r.json()
            if "access_token" not in data:
                raise AppError(ErrorCode.WECHAT_LOGIN_FAILED, "微信接口凭证获取失败")
            self._token = data["access_token"]
            self._token_expire = time.time() + int(data.get("expires_in", 7200))
            return self._token

    def get_phone_number(self, code: str) -> str:
        r = httpx.post(
            f"{self._BASE}/wxa/business/getuserphonenumber",
            params={"access_token": self._access_token()},
            json={"code": code},
            timeout=5,
        )
        data = r.json()
        phone = (data.get("phone_info") or {}).get("purePhoneNumber")
        if data.get("errcode") or not phone:
            raise AppError(ErrorCode.WECHAT_LOGIN_FAILED, "获取手机号失败")
        return phone


_fake = FakeWechat()
_real: RealWechat | None = None


def get_wechat() -> WechatMiniClient:
    global _real
    if settings.wechat_mode == "fake":
        return _fake
    if _real is None:
        _real = RealWechat()
    return _real
