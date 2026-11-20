"""回执服务商统一接口。每家服务商写一个适配器，实现 ReceiptProvider。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

ProviderResult = Literal["processing", "completed", "rejected", "failed"]


@dataclass
class SubmitRequest:
    attempt_ref: str  # 我们这边的尝试编号，服务商回调时会带回来
    provider_item_id: str  # 服务商那边的规格编号（provider_specs.provider_item_id）
    photo: bytes  # 已按规格导出的照片
    photo_mime: str
    form: dict[str, str]  # 姓名、身份证号等，已解密，只在内存里用
    region_code: str | None = None


@dataclass
class ProviderStatus:
    provider_order_no: str
    result: ProviderResult
    reject_reason: str | None = None
    image_code: str | None = None  # 回执上的图像号
    receipt_image: bytes | None = None  # 回执图片
    receipt_mime: str | None = None
    official_expire_at: datetime | None = None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderItem:
    provider_item_id: str
    name: str
    bg_colors: list[str]
    width_px: int
    height_px: int
    width_mm: int | None
    height_mm: int | None
    dpi: int
    file_size_min_kb: int | None
    file_size_max_kb: int | None
    sort: int
    raw: dict = field(default_factory=dict)


class ReceiptProvider(Protocol):
    code: str

    def submit(self, req: SubmitRequest) -> str:
        """提交办理，返回服务商订单号。网络超时等无法确认结果时抛 TimeoutError（不要当失败处理）。"""
        ...

    def query(self, provider_order_no: str) -> ProviderStatus: ...

    def list_items(self) -> list[ProviderItem]:
        """读取完整目录。网络超时抛 TimeoutError。"""
        ...

    def get_item(self, item_id: str) -> ProviderItem:
        """读取单条规格详情。网络超时抛 TimeoutError。"""
        ...

    def parse_callback(self, headers: dict[str, str], body: bytes) -> tuple[ProviderStatus, str]:
        """解析回调，返回 (状态, 去重键)。签名不对抛 AppError(CALLBACK_SIGNATURE_INVALID)。"""
        ...
