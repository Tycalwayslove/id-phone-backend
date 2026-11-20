"""回执服务商适配器。业务代码通过 get_provider 拿到统一接口。"""

from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.integrations.receipt_providers._zjz_common import build_callback_url
from app.integrations.receipt_providers.base import ReceiptProvider
from app.integrations.receipt_providers.fake import FakeProvider
from app.integrations.receipt_providers.qianweiyun import QianweiyunProvider
from app.integrations.receipt_providers.zheying import ZheyingProvider

_fake_instances: dict[str, FakeProvider] = {}


def get_provider(
    adapter: str,
    code: str,
    *,
    client: httpx.Client | None = None,
    callback_nonce: str | None = None,
) -> ReceiptProvider:
    """按 providers.adapter 选通道。传入 callback_nonce 时，返回的实例用于该次提交。"""
    if settings.receipt_mode == "fake":
        return _fake_instances.setdefault(code, FakeProvider(code))

    if adapter == "zheying":
        provider_class = ZheyingProvider
        base_url, app_key = settings.zheying_api_base, settings.zheying_app_key
    elif adapter == "qianweiyun":
        provider_class = QianweiyunProvider
        base_url, app_key = settings.qianweiyun_api_base, settings.qianweiyun_app_key
    else:
        raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "回执服务商适配器未配置")

    callback_url = f"{settings.public_base_url.rstrip('/')}/api/v1/callbacks/receipt/{quote(code, safe='')}"
    return provider_class(
        code,
        base_url=base_url,
        app_key=app_key,
        callback_url=callback_url,
        callback_nonce=callback_nonce,
        client=client,
    )


@contextmanager
def open_catalog_provider(adapter: str, code: str) -> Iterator[ReceiptProvider]:
    """在一次目录同步内复用连接。"""
    if settings.receipt_mode == "fake":
        yield get_provider(adapter, code)
    else:
        with httpx.Client() as client:
            yield get_provider(adapter, code, client=client)


__all__ = ["ReceiptProvider", "build_callback_url", "get_provider", "open_catalog_provider"]
