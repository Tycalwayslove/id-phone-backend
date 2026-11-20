"""统一错误：业务代码只抛 AppError(ErrorCode.XXX)，这里负责变成 {code, message} 返回给前端。

新增错误码：在 ErrorCode 里加一项，再在 _META 里写上 HTTP 状态码和默认提示。
"""

import logging
from enum import StrEnum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("app.errors")


class ErrorCode(StrEnum):
    # 通用
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    RATE_LIMITED = "RATE_LIMITED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DB_UNAVAILABLE = "DB_UNAVAILABLE"
    # 登录与权限
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_INVALID = "AUTH_INVALID"
    WECHAT_LOGIN_FAILED = "WECHAT_LOGIN_FAILED"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    PHONE_ALREADY_BOUND = "PHONE_ALREADY_BOUND"
    ADMIN_LOGIN_FAILED = "ADMIN_LOGIN_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    # 规格与照片
    SPEC_NOT_FOUND = "SPEC_NOT_FOUND"
    PHOTO_NOT_FOUND = "PHOTO_NOT_FOUND"
    PHOTO_ACCESS_EXPIRED = "PHOTO_ACCESS_EXPIRED"
    PHOTO_NOT_READY = "PHOTO_NOT_READY"
    PHOTO_REJECTED = "PHOTO_REJECTED"
    UPLOAD_NOT_FOUND = "UPLOAD_NOT_FOUND"
    UPLOAD_INVALID = "UPLOAD_INVALID"
    SPEC_CHANGE_NOT_ALLOWED = "SPEC_CHANGE_NOT_ALLOWED"
    # 套餐、订单、支付
    PLAN_NOT_AVAILABLE = "PLAN_NOT_AVAILABLE"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    ORDER_NOT_PAYABLE = "ORDER_NOT_PAYABLE"
    ORDER_NOT_CANCELLABLE = "ORDER_NOT_CANCELLABLE"
    PAYMENT_SIGNATURE_INVALID = "PAYMENT_SIGNATURE_INVALID"
    REFUND_NOT_ALLOWED = "REFUND_NOT_ALLOWED"
    # 权益
    ENTITLEMENT_NOT_FOUND = "ENTITLEMENT_NOT_FOUND"
    ENTITLEMENT_EXPIRED = "ENTITLEMENT_EXPIRED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    ONE_PERSON_MISMATCH = "ONE_PERSON_MISMATCH"
    # 回执
    RECEIPT_NOT_SUPPORTED = "RECEIPT_NOT_SUPPORTED"
    APPLICATION_NOT_FOUND = "APPLICATION_NOT_FOUND"
    APPLICATION_NOT_RESUBMITTABLE = "APPLICATION_NOT_RESUBMITTABLE"
    RESUBMIT_LIMIT_REACHED = "RESUBMIT_LIMIT_REACHED"
    RECEIPT_NOT_READY = "RECEIPT_NOT_READY"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    CALLBACK_SIGNATURE_INVALID = "CALLBACK_SIGNATURE_INVALID"


# 错误码 → (HTTP 状态码, 默认提示)
_META: dict[ErrorCode, tuple[int, str]] = {
    ErrorCode.VALIDATION_ERROR: (422, "请求参数不正确"),
    ErrorCode.NOT_FOUND: (404, "资源不存在"),
    ErrorCode.CONFLICT: (409, "数据已存在"),
    ErrorCode.METHOD_NOT_ALLOWED: (405, "不支持这种请求方式"),
    ErrorCode.RATE_LIMITED: (429, "操作太频繁，请稍后再试"),
    ErrorCode.IDEMPOTENCY_CONFLICT: (409, "同一个请求正在处理或参数不一致"),
    ErrorCode.INTERNAL_ERROR: (500, "服务开小差了，请稍后再试"),
    ErrorCode.DB_UNAVAILABLE: (503, "数据库暂时不可用，请稍后再试"),
    ErrorCode.AUTH_REQUIRED: (401, "请先登录"),
    ErrorCode.AUTH_INVALID: (401, "登录已失效，请重新登录"),
    ErrorCode.WECHAT_LOGIN_FAILED: (400, "微信登录失败，请重试"),
    ErrorCode.ACCOUNT_DISABLED: (403, "账号已被停用"),
    ErrorCode.PHONE_ALREADY_BOUND: (409, "这个手机号已绑定其他账号，请联系客服"),
    ErrorCode.ADMIN_LOGIN_FAILED: (401, "账号或密码错误"),
    ErrorCode.PERMISSION_DENIED: (403, "没有这个操作的权限"),
    ErrorCode.SPEC_NOT_FOUND: (404, "规格不存在"),
    ErrorCode.PHOTO_NOT_FOUND: (404, "照片不存在"),
    ErrorCode.PHOTO_ACCESS_EXPIRED: (403, "照片保管期已过，续费后可继续下载和换规格"),
    ErrorCode.PHOTO_NOT_READY: (409, "照片还在处理中"),
    ErrorCode.PHOTO_REJECTED: (403, "照片未通过内容检测，请更换照片"),
    ErrorCode.UPLOAD_NOT_FOUND: (404, "上传的文件不存在或已过期"),
    ErrorCode.UPLOAD_INVALID: (422, "上传的文件格式或大小不符合要求"),
    ErrorCode.SPEC_CHANGE_NOT_ALLOWED: (403, "当前权益不支持更换规格"),
    ErrorCode.PLAN_NOT_AVAILABLE: (409, "这个套餐暂不可购买"),
    ErrorCode.ORDER_NOT_FOUND: (404, "订单不存在"),
    ErrorCode.ORDER_NOT_PAYABLE: (409, "订单当前不能支付"),
    ErrorCode.ORDER_NOT_CANCELLABLE: (409, "订单当前不能取消"),
    ErrorCode.PAYMENT_SIGNATURE_INVALID: (401, "支付通知签名不正确"),
    ErrorCode.REFUND_NOT_ALLOWED: (409, "订单当前不能退款"),
    ErrorCode.ENTITLEMENT_NOT_FOUND: (404, "权益不存在"),
    ErrorCode.ENTITLEMENT_EXPIRED: (403, "权益已过期"),
    ErrorCode.QUOTA_EXHAUSTED: (409, "回执次数已用完"),
    ErrorCode.ONE_PERSON_MISMATCH: (403, "该权益仅限本人使用"),
    ErrorCode.RECEIPT_NOT_SUPPORTED: (409, "这个规格暂不支持办理回执"),
    ErrorCode.APPLICATION_NOT_FOUND: (404, "回执申请不存在"),
    ErrorCode.APPLICATION_NOT_RESUBMITTABLE: (409, "当前状态不能重新提交"),
    ErrorCode.RESUBMIT_LIMIT_REACHED: (409, "重新提交次数已用完"),
    ErrorCode.RECEIPT_NOT_READY: (409, "回执还没有出来"),
    ErrorCode.PROVIDER_UNAVAILABLE: (503, "回执通道暂时不可用，请稍后再试"),
    ErrorCode.CALLBACK_SIGNATURE_INVALID: (401, "回调签名不正确"),
}


def status_of(code: ErrorCode) -> int:
    return _META[code][0]


class AppError(Exception):
    """业务错误。抛出后由全局处理器转成统一格式返回。"""

    def __init__(self, code: ErrorCode, message: str | None = None):
        self.code = code
        self.status = _META[code][0]
        self.message = message or _META[code][1]
        super().__init__(f"{code}: {self.message}")


class FieldError(BaseModel):
    """一个参数的校验错误。"""

    field: str = Field(
        description="出错的参数位置，如 body.spec_code、query.limit", examples=["body.spec_code"]
    )
    message: str = Field(description="错误原因", examples=["Field required"])


class ErrorResponse(BaseModel):
    """所有接口出错时的统一返回格式。前端按 code 判断错误类型，message 可以直接展示给用户。"""

    code: str = Field(
        description="错误码，全大写下划线，完整列表见接口文档首页", examples=["QUOTA_EXHAUSTED"]
    )
    message: str = Field(description="给用户看的错误说明", examples=["回执次数已用完"])
    errors: list[FieldError] | None = Field(
        default=None, description="参数校验失败时，逐个列出出错的参数；其他错误为空"
    )


def error_doc(*codes: ErrorCode) -> dict:
    """在路由的 responses 里声明错误返回。同一个 HTTP 状态码的多个错误码合并成一条说明。"""
    return {
        "model": ErrorResponse,
        "description": "错误码：" + "、".join(f"{c}（{_META[c][1]}）" for c in codes),
    }


def errors_doc(*codes: ErrorCode) -> dict[int, dict]:
    """把一组错误码按 HTTP 状态码分组，直接传给路由的 responses=。"""
    grouped: dict[int, list[ErrorCode]] = {}
    for c in codes:
        grouped.setdefault(_META[c][0], []).append(c)
    return {status: error_doc(*cs) for status, cs in grouped.items()}


def error_catalog_markdown() -> str:
    """生成错误码表，放进接口文档首页。"""
    rows = "\n".join(f"| {c} | {s} | {m} |" for c, (s, m) in _META.items())
    return "| 错误码 | HTTP 状态 | 默认提示 |\n|---|---|---|\n" + rows


def _body(code: ErrorCode | str, message: str, errors: list[dict] | None = None) -> dict:
    return ErrorResponse(code=str(code), message=message, errors=errors).model_dump(exclude_none=True)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=_body(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"field": ".".join(str(p) for p in e.get("loc", ())), "message": e.get("msg", "")}
            for e in exc.errors()
        ]
        code = ErrorCode.VALIDATION_ERROR
        return JSONResponse(status_code=422, content=_body(code, _META[code][1], errors))

    @app.exception_handler(StarletteHTTPException)
    def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        mapping = {404: ErrorCode.NOT_FOUND, 405: ErrorCode.METHOD_NOT_ALLOWED}
        code = mapping.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        return JSONResponse(status_code=exc.status_code, content=_body(code, _META[code][1]))

    @app.exception_handler(Exception)
    def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=exc)
        code = ErrorCode.INTERNAL_ERROR
        return JSONResponse(status_code=500, content=_body(code, _META[code][1]))
