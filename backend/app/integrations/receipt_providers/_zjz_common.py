"""鹧应与黔微云共用的回执协议。"""

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
from contextlib import nullcontext
from urllib.parse import parse_qs

import httpx

from app.core.errors import AppError, ErrorCode
from app.integrations.receipt_providers._catalog import parse_item
from app.integrations.receipt_providers.base import (
    ProviderItem,
    ProviderResult,
    ProviderStatus,
    SubmitRequest,
)

log = logging.getLogger(__name__)

_MAKE = "/receipt/make"
_SUBMIT = "/receipt/submit"
# 服务商文档未给超时值。采用对接说明的 5 秒连接、30 秒读写超时。
_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
# 文档未说明 5MB 是否包含编码开销。按裸 Base64 不超过 5MB 处理。
_MAX_PHOTO_BYTES = 5_000_000 * 3 // 4
_RESULTS: dict[str, ProviderResult] = {
    "2": "processing",
    "3": "completed",
    "4": "completed",
    "-1": "rejected",
    "-2": "failed",
}
_LOGISTICS_FIELD = re.compile(r"logistics_info(?:\[([0-9]+)\])?\[(express_name|express_no)\]")


def _url(value: str, error_message: str) -> httpx.URL:
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL:
        pass
    else:
        if url.scheme in ("http", "https") and url.host and not url.userinfo and not url.fragment:
            return url
    raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, error_message)


def build_callback_url(callback_url: str, *, nonce: str | None = None) -> tuple[str, str]:
    """返回带 nonce 的回调 URL 与 nonce。业务层可在提交前将其摘要绑定到 attempt。"""
    url = _url(callback_url, "回执服务商回调地址无效")
    nonce = secrets.token_urlsafe(32) if nonce is None else nonce
    if not nonce:
        raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "回执回调校验参数无效")
    return str(url.copy_set_param("nonce", nonce)), nonce


def _logistics(form: dict[str, list[str]]) -> list[dict[str, str]]:
    # 文档未说明表单如何编码数组。识别 JSON 和方括号字段，只取文档列出的物流字段。
    if "logistics_info" in form:
        try:
            items = json.loads(_field(form, "logistics_info"))
        except ValueError, RecursionError:
            return []
    else:
        bracket_items: dict[str | None, dict[str, str]] = {}
        for key, values in form.items():
            if len(values) == 1 and (match := _LOGISTICS_FIELD.fullmatch(key)):
                index, field = match.groups()
                bracket_items.setdefault(index, {})[field] = values[0]
        items = list(bracket_items.values())

    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return []
    return [
        {"express_name": name, "express_no": number}
        for item in items
        if isinstance(item, dict)
        and isinstance(name := item.get("express_name"), str)
        and isinstance(number := item.get("express_no"), str)
    ]


def _field(form: dict[str, list[str]], key: str) -> str:
    values = form.get(key, [])
    return values[0] if len(values) == 1 else ""


def _id_as_text(value: object) -> str:
    if type(value) is int and value > 0:
        return str(value)
    if isinstance(value, str) and value.strip():
        return value
    return ""


class ZjzReceiptProvider:
    def __init__(
        self,
        code: str,
        *,
        base_url: str,
        app_key: str,
        callback_url: str,
        callback_nonce: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.code = code
        self._base_url = base_url
        self._app_key = app_key
        self._callback_url = callback_url
        self._callback_nonce = callback_nonce
        self._client = client

    def _api_base(self) -> str:
        base = _url(self._base_url, "回执服务商 API 地址无效")
        if not self._app_key or base.scheme != "https" or base.query:
            raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "回执服务商 API 配置无效")
        return str(base).rstrip("/")

    def submit(self, req: SubmitRequest) -> str:
        base_url = self._api_base()
        if req.photo_mime not in ("image/jpeg", "image/png") or not 0 < len(req.photo) <= _MAX_PHOTO_BYTES:
            raise AppError(ErrorCode.UPLOAD_INVALID)
        if not req.provider_item_id.isascii() or not req.provider_item_id.isdecimal():
            raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "回执服务商规格编号无效")
        notice_url, _ = build_callback_url(self._callback_url, nonce=self._callback_nonce)

        # 规格的 param 键名文档未给全。调用方先按 ProviderSpec.param_mapping 转换。
        form = {"notice_url": notice_url}
        if req.form:
            form["param"] = json.dumps(req.form, ensure_ascii=False)
        # 沙箱、限流、驳回重提计费和 pic_id 复用规则均未说明。每次仅执行一组请求，由 make 校验分辨率。
        with nullcontext(self._client) if self._client is not None else httpx.Client() as client:
            pic_id = self._post_id(
                client,
                base_url,
                _MAKE,
                {"item_id": req.provider_item_id, "image": base64.b64encode(req.photo).decode("ascii")},
                "pic_id",
            )
            if not pic_id.isascii() or not pic_id.isdecimal():
                raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "回执服务商制作编号无效")
            form["pic_id"] = pic_id
            return self._post_id(client, base_url, _SUBMIT, form, "order_no")

    def _post_id(
        self, client: httpx.Client, base_url: str, path: str, form: dict[str, str], id_field: str
    ) -> str:
        data = self._post(client, base_url, path, form)
        if identifier := _id_as_text(data.get(id_field)):
            return identifier
        if path == _SUBMIT:
            raise TimeoutError(f"回执服务商 {path} 结果未知")
        raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "回执服务商制作请求失败")

    def _post(self, client: httpx.Client, base_url: str, path: str, form: dict[str, str]) -> dict:
        try:
            # 请求侧未给出 timestamp、nonce 或 HMAC 规则，服务商凭据按文档放在表单 key 字段。
            response = client.post(
                base_url + path,
                data={"key": self._app_key, **form},
                timeout=_TIMEOUT,
                follow_redirects=False,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.TimeoutException:
            raise_timeout = True
        except httpx.HTTPError, ValueError, RecursionError:
            raise_timeout = False
        else:
            if isinstance(body, dict) and type(body.get("code")) is int:
                if body["code"] != 0:
                    # 完整错误码表和余额不足行为未公开。msg 可能回显密钥或表单，只保留固定说明。
                    raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, f"回执服务商拒绝 {path} 请求")
                data = body.get("data")
                if isinstance(data, dict):
                    return data
            raise_timeout = False

        # 离开 except 后再抛出，避免异常链携带原请求。submit 缺少可确认结果时也走人工核对。
        # 文档未说明幂等键和外部单号，不自动重试任一阶段。
        if raise_timeout or path == _SUBMIT:
            raise TimeoutError(f"回执服务商 {path} 结果未知")
        raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, f"回执服务商 {path} 请求失败")

    def _catalog_post(self, path: str, form: dict[str, str]) -> dict:
        base_url = self._api_base()
        with nullcontext(self._client) if self._client is not None else httpx.Client() as client:
            return self._post(client, base_url, path, form)

    def list_items(self) -> list[ProviderItem]:
        rows = self._catalog_post("/item/list", {}).get("list")
        if not isinstance(rows, list):
            raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "回执服务商目录无效")
        return [parse_item(row, id_field="item_id") for row in rows]

    def get_item(self, item_id: str) -> ProviderItem:
        item = parse_item(self._catalog_post("/item/get", {"item_id": item_id}), id_field="id")
        if item.provider_item_id != item_id:
            raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "回执服务商详情规格编号不匹配")
        return item

    def query(self, provider_order_no: str) -> ProviderStatus:
        # 服务商未公开订单查询接口。保持 processing，交由业务层等回调或超时转人工。
        return ProviderStatus(provider_order_no=provider_order_no, result="processing")

    def parse_callback(self, headers: dict[str, str], body: bytes) -> tuple[ProviderStatus, str]:
        try:
            form = parse_qs(
                body.decode("utf-8"), keep_blank_values=True, strict_parsing=True, errors="strict"
            )
        except ValueError:
            form = None
        if form is None:
            raise AppError(ErrorCode.VALIDATION_ERROR, "回执回调表单无效")

        # 回调重推策略和来源 IP 未说明。静态签名之外，nonce、订单归属与重放由接收端处理。
        expected = hashlib.md5(self._app_key.encode("utf-8")).hexdigest().encode("ascii")
        if not self._app_key or not hmac.compare_digest(expected, _field(form, "sign").encode("utf-8")):
            raise AppError(ErrorCode.CALLBACK_SIGNATURE_INVALID)

        order_no, state = _field(form, "order_no"), _field(form, "status")
        if not order_no.strip() or not state.strip():
            raise AppError(ErrorCode.VALIDATION_ERROR, "回执回调缺少订单号或状态")
        result = _RESULTS.get(state)
        if result is None:
            log.warning("收到未识别的回执服务商状态")
            result = "processing"

        status = ProviderStatus(provider_order_no=order_no, result=result, raw={"status": state})
        if state == "3":
            # 图片有效期和鉴权未说明。校验订单归属后异步下载，图像号和官方有效期保留为空。
            if image_url := _field(form, "image_receipt"):
                status.raw["image_receipt"] = image_url
        elif state == "4":
            if logistics := _logistics(form):
                status.raw["logistics_info"] = logistics
        elif state == "-1":
            # 文档未区分审核驳回与系统异常。按驳回处理，原因使用服务商给出的文本。
            status.reject_reason = _field(form, "reject_msg") or None
        return status, f"{self.code}:{order_no}:{state}"
