"""假回执通道：用于开发联调和自动化测试。

- submit 后状态为 processing
- 开发接口 / 测试调用 simulate(order_no, "completed" | "rejected" | "failed", reason) 改变结果
- 回调：JSON body {"provider_order_no", "result", "reject_reason"}，签名放 X-Fake-Signature
"""

import io
import json
import secrets

from app.core.errors import AppError, ErrorCode
from app.core.security import sign
from app.integrations.receipt_providers.base import ProviderStatus, SubmitRequest


def sign_fake_callback(body: bytes) -> str:
    return sign("fake-receipt:" + body.decode())


def _receipt_png(order_no: str) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (600, 400), "white")
    ImageDraw.Draw(img).text((40, 180), f"FAKE RECEIPT {order_no}", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class FakeProvider:
    def __init__(self, code: str) -> None:
        self.code = code
        self._state: dict[str, ProviderStatus] = {}

    def submit(self, req: SubmitRequest) -> str:
        order_no = f"FAKE-{req.attempt_ref}-{secrets.token_hex(3)}"
        self._state[order_no] = ProviderStatus(provider_order_no=order_no, result="processing")
        return order_no

    def simulate(self, order_no: str, result: str, reason: str | None = None) -> ProviderStatus:
        status = ProviderStatus(provider_order_no=order_no, result=result)  # type: ignore[arg-type]
        if result == "completed":
            status.image_code = "IMG" + secrets.token_hex(4).upper()
            status.receipt_image = _receipt_png(order_no)
            status.receipt_mime = "image/png"
        elif result == "rejected":
            status.reject_reason = reason or "照片不符合要求：背景不均匀"
        self._state[order_no] = status
        return status

    def query(self, provider_order_no: str) -> ProviderStatus:
        return self._state.get(
            provider_order_no, ProviderStatus(provider_order_no=provider_order_no, result="processing")
        )

    def parse_callback(self, headers: dict[str, str], body: bytes) -> tuple[ProviderStatus, str]:
        if headers.get("x-fake-signature") != sign_fake_callback(body):
            raise AppError(ErrorCode.CALLBACK_SIGNATURE_INVALID)
        data = json.loads(body)
        status = self.simulate(data["provider_order_no"], data["result"], data.get("reject_reason"))
        return status, f"{self.code}:{data['provider_order_no']}:{data['result']}"
