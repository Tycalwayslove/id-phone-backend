"""支付：下单拿到小程序拉起支付需要的参数、解析支付结果通知、退款。

fake 模式（默认）不访问微信支付：
- create_prepay 返回 {"mode": "fake", ...}，前端看到 mode=fake 时不调 wx.requestPayment，
  而是调开发接口 POST /api/v1/dev/orders/{order_no}/simulate-paid 模拟支付成功
- parse_notify 接受 JSON 通知，签名放在 X-Fake-Signature 头里（值为 sign_fake_notify(body)）
"""

import json
from dataclasses import dataclass
from typing import Protocol

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.security import sign


@dataclass
class PayNotify:
    out_trade_no: str
    transaction_id: str
    amount_fen: int
    success: bool
    raw: dict


class PaymentGateway(Protocol):
    channel: str

    def create_prepay(self, *, out_trade_no: str, amount_fen: int, description: str, openid: str) -> dict: ...
    def parse_notify(self, headers: dict[str, str], body: bytes) -> PayNotify: ...
    def refund(
        self, *, out_trade_no: str, out_refund_no: str, refund_fen: int, total_fen: int, reason: str
    ) -> str: ...


def sign_fake_notify(body: bytes) -> str:
    return sign("fake-pay:" + body.decode())


class FakePay:
    channel = "wxpay"

    def create_prepay(self, *, out_trade_no: str, amount_fen: int, description: str, openid: str) -> dict:
        return {"mode": "fake", "out_trade_no": out_trade_no, "amount_fen": amount_fen}

    def parse_notify(self, headers: dict[str, str], body: bytes) -> PayNotify:
        if headers.get("x-fake-signature") != sign_fake_notify(body):
            raise AppError(ErrorCode.PAYMENT_SIGNATURE_INVALID)
        data = json.loads(body)
        return PayNotify(
            out_trade_no=data["out_trade_no"],
            transaction_id=data["transaction_id"],
            amount_fen=int(data["amount_fen"]),
            success=bool(data.get("success", True)),
            raw=data,
        )

    def refund(
        self, *, out_trade_no: str, out_refund_no: str, refund_fen: int, total_fen: int, reason: str
    ) -> str:
        return "success"


class WechatPay:
    """微信支付 APIv3。需要商户号、APIv3 密钥、商户证书后实现，见 docs/progress.md 待办。"""

    channel = "wxpay"

    def create_prepay(self, **_: object) -> dict:
        raise AppError(ErrorCode.INTERNAL_ERROR, "微信支付尚未配置")

    def parse_notify(self, headers: dict[str, str], body: bytes) -> PayNotify:
        raise AppError(ErrorCode.PAYMENT_SIGNATURE_INVALID)

    def refund(self, **_: object) -> str:
        raise AppError(ErrorCode.INTERNAL_ERROR, "微信支付尚未配置")


def get_payment() -> PaymentGateway:
    return FakePay() if settings.pay_mode == "fake" else WechatPay()
