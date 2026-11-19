"""回执服务商适配器。业务代码只通过 get_provider(adapter) 拿到统一接口。"""

from app.core.config import settings
from app.integrations.receipt_providers.base import ReceiptProvider
from app.integrations.receipt_providers.fake import FakeProvider

_fake_instances: dict[str, FakeProvider] = {}


def get_provider(adapter: str, code: str) -> ReceiptProvider:
    """adapter 是 providers.adapter 字段的值（如 zheying、clipimg）。fake 模式下统一用假通道。"""
    if settings.receipt_mode == "fake":
        return _fake_instances.setdefault(code, FakeProvider(code))
    raise NotImplementedError(f"回执服务商 {adapter} 的正式接入待实现")


__all__ = ["ReceiptProvider", "get_provider"]
