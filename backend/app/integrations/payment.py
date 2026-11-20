"""微信支付 APIv3 与本地联调用的支付适配器。"""

import base64
import json
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import quote, urlsplit

import httpx
from cryptography import x509
from cryptography.exceptions import InvalidSignature, InvalidTag, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings, settings
from app.core.errors import AppError, ErrorCode
from app.core.security import sign

PAY_NOTIFY_PATH = "/api/v1/callbacks/wxpay"
REFUND_NOTIFY_PATH = "/api/v1/callbacks/wxpay/refund"
_API = "https://api.mch.weixin.qq.com"
_SCHEME = "WECHATPAY2-SHA256-RSA2048"
_ORDER_PATH = "/v3/pay/transactions/out-trade-no"
_REFUND_PATH = "/v3/refund/domestic/refunds"

type RefundStatus = Literal["pending", "success", "failed"]


@dataclass
class PayNotify:
    out_trade_no: str
    transaction_id: str
    amount_fen: int
    success: bool
    raw: dict


@dataclass(frozen=True)
class OrderQuery:
    trade_state: str
    payment: PayNotify | None = None


@dataclass(frozen=True)
class RefundResult:
    out_trade_no: str
    out_refund_no: str
    transaction_id: str
    refund_fen: int
    total_fen: int
    status: RefundStatus


class PaymentGateway(Protocol):
    channel: str

    def create_prepay(
        self,
        *,
        out_trade_no: str,
        amount_fen: int,
        description: str,
        openid: str,
        expire_at: datetime | None = None,
    ) -> dict: ...
    def parse_notify(self, headers: Mapping[str, str], body: bytes) -> PayNotify: ...
    def query_order(self, out_trade_no: str) -> OrderQuery: ...
    def close_order(self, out_trade_no: str) -> None: ...
    def refund(
        self, *, out_trade_no: str, out_refund_no: str, refund_fen: int, total_fen: int, reason: str
    ) -> RefundStatus: ...
    def query_refund(self, out_refund_no: str) -> RefundResult | None: ...
    def parse_refund_notify(self, headers: Mapping[str, str], body: bytes) -> RefundResult: ...


def sign_fake_notify(body: bytes) -> str:
    return sign("fake-pay:" + body.decode())


class FakePay:
    channel = "wxpay"

    def create_prepay(
        self,
        *,
        out_trade_no: str,
        amount_fen: int,
        description: str,
        openid: str,
        expire_at: datetime | None = None,
    ) -> dict:
        return {"mode": "fake", "out_trade_no": out_trade_no, "amount_fen": amount_fen}

    def parse_notify(self, headers: Mapping[str, str], body: bytes) -> PayNotify:
        if not secrets.compare_digest(
            headers.get("x-fake-signature", "").encode(), sign_fake_notify(body).encode()
        ):
            raise AppError(ErrorCode.PAYMENT_SIGNATURE_INVALID)
        data = json.loads(body)
        return PayNotify(
            out_trade_no=data["out_trade_no"],
            transaction_id=data["transaction_id"],
            amount_fen=int(data["amount_fen"]),
            success=bool(data.get("success", True)),
            raw=data,
        )

    def query_order(self, out_trade_no: str) -> OrderQuery:
        return OrderQuery("NOTPAY")

    def close_order(self, out_trade_no: str) -> None:
        pass

    def refund(
        self, *, out_trade_no: str, out_refund_no: str, refund_fen: int, total_fen: int, reason: str
    ) -> RefundStatus:
        return "success"

    def query_refund(self, out_refund_no: str) -> RefundResult | None:
        return None

    def parse_refund_notify(self, headers: Mapping[str, str], body: bytes) -> RefundResult:
        raise AppError(ErrorCode.PAYMENT_SIGNATURE_INVALID)


class _WechatRequestError(AppError):
    def __init__(self, status: int = 0, code: str = "", *, verified: bool = False):
        super().__init__(ErrorCode.INTERNAL_ERROR, "微信支付请求暂未完成，请稍后重试")
        self.upstream_status = status
        self.upstream_code = code
        self.verified = verified


def _required_text(data: dict, field: str) -> str:
    value = data[field]
    if not isinstance(value, str) or not value:
        raise ValueError(field)
    return value


def _positive_fen(data: dict, field: str) -> int:
    value = data[field]
    if type(value) is not int or value <= 0:
        raise ValueError(field)
    return value


def _json_object(body: bytes) -> dict:
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("expected object")
    return data


class WechatPay:
    """直连商户 APIv3 客户端。信任根来自本地配置的证书或微信支付公钥。"""

    channel = "wxpay"

    def __init__(self, config: Settings | None = None, *, transport: httpx.BaseTransport | None = None):
        self.config = config if config is not None else settings
        self.transport = transport
        try:
            self.private_key, self.verifiers, self.verify_serial, self.cipher = self._load_credentials()
        except OSError, TypeError, ValueError, UnsupportedAlgorithm:
            raise AppError(ErrorCode.INTERNAL_ERROR, "微信支付密钥或证书配置不正确") from None

    def _load_credentials(self) -> tuple[rsa.RSAPrivateKey, dict[str, rsa.RSAPublicKey], str, AESGCM]:
        cfg = self.config
        api_key = cfg.wxpay_api_v3_key.encode()
        if len(api_key) != 32 or not all((cfg.wx_mini_app_id, cfg.wxpay_mch_id, cfg.wxpay_cert_serial)):
            raise ValueError("merchant settings")
        private_key = serialization.load_pem_private_key(Path(cfg.wxpay_private_key_path).read_bytes(), None)
        if not isinstance(private_key, rsa.RSAPrivateKey) or private_key.key_size != 2048:
            raise ValueError("merchant key")

        verifiers: dict[str, rsa.RSAPublicKey] = {}
        cert_serial = ""
        if cfg.wxpay_platform_cert_path:
            # 支持将轮换期间的新旧平台证书放在同一 PEM 文件中。
            for cert in x509.load_pem_x509_certificates(Path(cfg.wxpay_platform_cert_path).read_bytes()):
                key = cert.public_key()
                if not isinstance(key, rsa.RSAPublicKey):
                    raise ValueError("platform certificate key")
                cert_serial = f"{cert.serial_number:X}"
                verifiers[cert_serial] = key
        if cfg.wxpay_public_key_path or cfg.wxpay_public_key_id:
            if not cfg.wxpay_public_key_id.startswith("PUB_KEY_ID_"):
                raise ValueError("platform key ID")
            key = serialization.load_pem_public_key(Path(cfg.wxpay_public_key_path).read_bytes())
            if not isinstance(key, rsa.RSAPublicKey):
                raise ValueError("platform public key")
            verifiers[cfg.wxpay_public_key_id] = key
        if not verifiers:
            raise ValueError("no platform verification keys")
        return private_key, verifiers, cfg.wxpay_public_key_id or cert_serial, AESGCM(api_key)

    def _sign(self, message: bytes) -> str:
        return base64.b64encode(self.private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())).decode()

    def _verify(self, headers: Mapping[str, str], body: bytes) -> None:
        headers = {name.lower(): value for name, value in headers.items()}
        try:
            timestamp = headers["wechatpay-timestamp"]
            nonce = headers["wechatpay-nonce"]
            if (
                not nonce
                or not timestamp.isascii()
                or not timestamp.isdecimal()
                or abs(int(time.time()) - int(timestamp)) > 300
            ):
                raise ValueError("signature timestamp or nonce")
            if headers.get("wechatpay-signature-type", _SCHEME) != _SCHEME:
                raise ValueError("signature type")
            serial = headers["wechatpay-serial"]
            signature = base64.b64decode(headers["wechatpay-signature"], validate=True)
            key = self.verifiers[serial]
            key.verify(
                signature,
                f"{timestamp}\n{nonce}\n".encode() + body + b"\n",
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except KeyError, ValueError, InvalidSignature:
            raise AppError(ErrorCode.PAYMENT_SIGNATURE_INVALID) from None

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        payload: dict | None = None,
        expected_status: int = 200,
    ) -> dict:
        with httpx.Client(base_url=_API, transport=self.transport, timeout=5, trust_env=False) as client:
            body = (
                b""
                if payload is None
                else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            )
            request = client.build_request(
                method, path, params=params, content=body, headers={"Accept": "application/json"}
            )
            if payload is not None:
                request.headers["Content-Type"] = "application/json"
            timestamp, nonce = str(int(time.time())), secrets.token_hex(16)
            message = b"\n".join(
                (method.encode(), request.url.raw_path, timestamp.encode(), nonce.encode(), body, b"")
            )
            signature = self._sign(message)
            request.headers["Authorization"] = (
                f'{_SCHEME} mchid="{self.config.wxpay_mch_id}",nonce_str="{nonce}",'
                f'timestamp="{timestamp}",serial_no="{self.config.wxpay_cert_serial}",signature="{signature}"'
            )
            request.headers["Wechatpay-Serial"] = self.verify_serial
            try:
                response = client.send(request)
            except httpx.RequestError:
                raise _WechatRequestError from None

        signed = "Wechatpay-Signature" in response.headers
        if response.is_success or signed:
            try:
                self._verify(response.headers, response.content)
            except AppError:
                raise _WechatRequestError from None
        try:
            data = _json_object(response.content) if response.content else {}
        except ValueError:
            raise _WechatRequestError from None
        if response.status_code != expected_status:
            raise _WechatRequestError(response.status_code, data.get("code", ""), verified=signed)
        return data

    def _notify_url(self, configured: str, path: str) -> str:
        url = configured or self.config.public_base_url.rstrip("/") + path
        try:
            parsed = urlsplit(url)
            if (
                parsed.scheme == "https"
                and parsed.hostname
                and parsed.username is None
                and not (parsed.query or parsed.fragment)
            ):
                return url
        except ValueError:
            pass
        raise AppError(ErrorCode.INTERNAL_ERROR, "微信支付通知地址必须是无参数的公网 HTTPS 地址")

    def create_prepay(
        self,
        *,
        out_trade_no: str,
        amount_fen: int,
        description: str,
        openid: str,
        expire_at: datetime | None = None,
    ) -> dict:
        if not openid:
            raise AppError(ErrorCode.ORDER_NOT_PAYABLE, "用户未绑定微信小程序身份")
        app_id = self.config.wx_mini_app_id
        payload = {
            "appid": app_id,
            "mchid": self.config.wxpay_mch_id,
            "description": description[:127],
            "out_trade_no": out_trade_no,
            "notify_url": self._notify_url(self.config.wxpay_notify_url, PAY_NOTIFY_PATH),
            "amount": {"total": amount_fen, "currency": "CNY"},
            "payer": {"openid": openid},
        }
        if expire_at is not None:
            payload["time_expire"] = expire_at.isoformat(timespec="seconds")
        data = self._request("POST", "/v3/pay/transactions/jsapi", payload=payload)
        try:
            package = "prepay_id=" + _required_text(data, "prepay_id")
        except KeyError, ValueError:
            raise _WechatRequestError from None
        timestamp, nonce = str(int(time.time())), secrets.token_hex(16)
        return {
            "timeStamp": timestamp,
            "nonceStr": nonce,
            "package": package,
            "signType": "RSA",
            "paySign": self._sign(f"{app_id}\n{timestamp}\n{nonce}\n{package}\n".encode()),
        }

    def _payment(self, data: dict) -> PayNotify:
        if data["appid"] != self.config.wx_mini_app_id or data["mchid"] != self.config.wxpay_mch_id:
            raise ValueError("merchant or app")
        amount = data["amount"]
        if not isinstance(amount, dict) or amount.get("currency", "CNY") != "CNY":
            raise ValueError("currency")
        return PayNotify(
            out_trade_no=_required_text(data, "out_trade_no"),
            transaction_id=_required_text(data, "transaction_id"),
            amount_fen=_positive_fen(amount, "total"),
            success=True,
            raw=data,
        )

    def _decrypt_notify(
        self, headers: Mapping[str, str], body: bytes, original_type: str
    ) -> tuple[str, dict]:
        self._verify(headers, body)
        try:
            envelope = _json_object(body)
            resource = envelope["resource"]
            if (
                envelope["resource_type"] != "encrypt-resource"
                or resource["original_type"] != original_type
                or resource["algorithm"] != "AEAD_AES_256_GCM"
            ):
                raise ValueError("resource type or algorithm")
            aad = resource.get("associated_data", "")
            if not isinstance(aad, str):
                raise ValueError("associated data")
            nonce = _required_text(resource, "nonce").encode()
            if len(nonce) != 12:
                raise ValueError("nonce length")
            encrypted = base64.b64decode(_required_text(resource, "ciphertext"), validate=True)
            plaintext = self.cipher.decrypt(nonce, encrypted, aad.encode())
            return _required_text(envelope, "event_type"), _json_object(plaintext)
        except KeyError, TypeError, ValueError, InvalidTag:
            raise AppError(ErrorCode.VALIDATION_ERROR, "微信支付通知无法解密或格式不正确") from None

    def parse_notify(self, headers: Mapping[str, str], body: bytes) -> PayNotify:
        event, data = self._decrypt_notify(headers, body, "transaction")
        try:
            if event != "TRANSACTION.SUCCESS" or data["trade_state"] != "SUCCESS":
                raise ValueError("payment event")
            return self._payment(data)
        except KeyError, TypeError, ValueError:
            raise AppError(ErrorCode.VALIDATION_ERROR, "微信支付通知内容不匹配") from None

    def query_order(self, out_trade_no: str) -> OrderQuery:
        data = self._request(
            "GET", f"{_ORDER_PATH}/{quote(out_trade_no, safe='')}", params={"mchid": self.config.wxpay_mch_id}
        )
        try:
            if (
                data["out_trade_no"] != out_trade_no
                or data["appid"] != self.config.wx_mini_app_id
                or data["mchid"] != self.config.wxpay_mch_id
            ):
                raise ValueError("merchant, app or order")
            state = _required_text(data, "trade_state")
            return OrderQuery(state, self._payment(data) if state == "SUCCESS" else None)
        except KeyError, TypeError, ValueError:
            raise _WechatRequestError from None

    def close_order(self, out_trade_no: str) -> None:
        try:
            self._request(
                "POST",
                f"{_ORDER_PATH}/{quote(out_trade_no, safe='')}/close",
                payload={"mchid": self.config.wxpay_mch_id},
                expected_status=204,
            )
        except _WechatRequestError as error:
            # 一次关单可能已成功但应答丢失，也可能与付款竞争。以已验签的查单结果为准。
            order = self.query_order(out_trade_no)
            if order.trade_state in ("SUCCESS", "REFUND"):
                raise AppError(ErrorCode.ORDER_NOT_CANCELLABLE) from None
            if order.trade_state != "CLOSED":
                raise error

    def refund(
        self, *, out_trade_no: str, out_refund_no: str, refund_fen: int, total_fen: int, reason: str
    ) -> RefundStatus:
        payload = {
            "out_trade_no": out_trade_no,
            "out_refund_no": out_refund_no,
            "reason": reason.encode()[:80].decode(errors="ignore"),
            "notify_url": self._notify_url(self.config.wxpay_refund_notify_url, REFUND_NOTIFY_PATH),
            "amount": {"refund": refund_fen, "total": total_fen, "currency": "CNY"},
        }
        try:
            self._request("POST", _REFUND_PATH, payload=payload)
        except _WechatRequestError as error:
            if error.verified and (error.upstream_status, error.upstream_code) in (
                (400, "INVALID_REQUEST"),
                (400, "PARAM_ERROR"),
                (403, "USER_ACCOUNT_ABNORMAL"),
            ):
                return "failed"
            # 超时、未验过的应答等无法确认是否受理。保留退款流水和余额占用。
        return "pending"

    @staticmethod
    def _refund_result(data: dict, state: str) -> RefundResult:
        # 异常退款仍可由商户处理成功，因此继续占用余额。
        statuses: dict[str, RefundStatus] = {
            "SUCCESS": "success",
            "CLOSED": "failed",
            "PROCESSING": "pending",
            "ABNORMAL": "pending",
        }
        amount = data["amount"]
        if not isinstance(amount, dict) or amount.get("currency", "CNY") != "CNY":
            raise ValueError("currency")
        return RefundResult(
            out_trade_no=_required_text(data, "out_trade_no"),
            out_refund_no=_required_text(data, "out_refund_no"),
            transaction_id=_required_text(data, "transaction_id"),
            refund_fen=_positive_fen(amount, "refund"),
            total_fen=_positive_fen(amount, "total"),
            status=statuses[state],
        )

    def query_refund(self, out_refund_no: str) -> RefundResult | None:
        try:
            data = self._request("GET", f"{_REFUND_PATH}/{quote(out_refund_no, safe='')}")
        except _WechatRequestError as error:
            if (error.upstream_status, error.upstream_code) == (404, "RESOURCE_NOT_EXISTS"):
                return None
            raise
        try:
            if data["out_refund_no"] != out_refund_no:
                raise ValueError("refund number")
            return self._refund_result(data, data["status"])
        except KeyError, TypeError, ValueError:
            raise _WechatRequestError from None

    def parse_refund_notify(self, headers: Mapping[str, str], body: bytes) -> RefundResult:
        event, data = self._decrypt_notify(headers, body, "refund")
        try:
            if (
                data["mchid"] != self.config.wxpay_mch_id
                or event not in ("REFUND.SUCCESS", "REFUND.CLOSED", "REFUND.ABNORMAL")
                or event != f"REFUND.{data['refund_status']}"
            ):
                raise ValueError("refund event or merchant")
            return self._refund_result(data, data["refund_status"])
        except KeyError, TypeError, ValueError:
            raise AppError(ErrorCode.VALIDATION_ERROR, "微信退款通知内容不匹配") from None


def get_payment() -> PaymentGateway:
    return FakePay() if settings.pay_mode == "fake" else WechatPay()
