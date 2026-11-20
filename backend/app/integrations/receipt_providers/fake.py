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
from app.integrations.receipt_providers._catalog import parse_item
from app.integrations.receipt_providers.base import ProviderItem, ProviderStatus, SubmitRequest

# 同时覆盖 seed_dev 已配置的回执规格，方便演示更新和新建。
_ITEMS = (
    ("1001", "一寸", 295, 413, 25, 35, "['blue','white','red']", 20, 200),
    ("1002", "二寸", 413, 579, 35, 49, "['blue','white','red']", 30, 200),
    ("1003", "小一寸", 260, 378, 22, 32, "['sky_blue','gray','dark_red','pose_1']", 20, 100),
    ("713", "广东身份证（回执）", 358, 441, 26, 32, "['white']", 20, 100),
    ("625", "贵州身份证（回执）", 358, 441, 26, 32, "['white']", 20, 100),
    ("755", "安徽身份证（回执）", 358, 441, 26, 32, "['white']", 20, 100),
    ("712", "广东社保卡", 358, 441, 26, 32, "['white']", 15, 50),
    ("622", "广东驾驶证", 413, 579, 35, 49, "['white']", 20, 100),
    ("736", "贵州驾驶证", 413, 579, 35, 49, "['white']", 20, 100),
    ("714", "广东居住证", 358, 441, 26, 32, "['white']", 20, 100),
    ("1004", "护照", 390, 567, 33, 48, "['white']", 30, 80),
    ("624", "港澳通行证", 390, 567, 33, 48, "['white']", 30, 80),
    ("1005", "教师资格证", 295, 413, 25, 35, "['white']", 20, 200),
    ("1006", "普通话考试", 390, 567, 33, 48, "['blue','white']", 20, 200),
)
_RECEIPT_ITEMS = {"713", "625", "755", "712", "622", "736", "714"}


def _catalog() -> list[ProviderItem]:
    return [
        parse_item(
            dict(
                item_id=item_id,
                name=name,
                width_px=wpx,
                height_px=hpx,
                width_mm=wmm,
                height_mm=hmm,
                color=color,
                dpi=300,
                sort=sort,
                file_size_min=size_min,
                file_size_max=size_max,
                is_receipt="1" if item_id in _RECEIPT_ITEMS else "0",
                receipt_param=json.dumps(["text_mobile", "text_city", "text_name", "text_idcard"])
                if item_id in _RECEIPT_ITEMS
                else "[]",
                category="1" if sort < 3 else "2" if item_id in {"1004", "624"} else "3",
            ),
            id_field="item_id",
        )
        for sort, (item_id, name, wpx, hpx, wmm, hmm, color, size_min, size_max) in enumerate(_ITEMS)
    ]


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

    def list_items(self) -> list[ProviderItem]:
        return _catalog()

    def get_item(self, item_id: str) -> ProviderItem:
        for item in self.list_items():
            if item.provider_item_id == item_id:
                return item
        raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "回执服务商规格不存在")

    def parse_callback(self, headers: dict[str, str], body: bytes) -> tuple[ProviderStatus, str]:
        if headers.get("x-fake-signature") != sign_fake_callback(body):
            raise AppError(ErrorCode.CALLBACK_SIGNATURE_INVALID)
        data = json.loads(body)
        status = self.simulate(data["provider_order_no"], data["result"], data.get("reject_reason"))
        return status, f"{self.code}:{data['provider_order_no']}:{data['result']}"
