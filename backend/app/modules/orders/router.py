import logging
from collections.abc import Callable, Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.deps import DB, IdempotencyKeyHeader, Me, Page
from app.core.errors import AppError, ErrorCode, errors_doc
from app.modules.orders import service
from app.modules.orders.schemas import (
    OrderCreatedOut,
    OrderCreateIn,
    OrderOut,
    OrderPage,
    PlanOut,
    WxpayFailure,
)

router = APIRouter(tags=["套餐与订单"])
callback_router = APIRouter(tags=["回调"])
dev_router = APIRouter(tags=["联调"])
log = logging.getLogger(__name__)

_AUTH = (ErrorCode.AUTH_REQUIRED, ErrorCode.AUTH_INVALID)

OrderNoPath = Annotated[
    str, Path(description="订单号，下单或订单列表接口返回的 order_no", examples=["O20261119083012A1B2C3"])
]


@router.get(
    "/plans",
    operation_id="plans_list",
    summary="在售套餐列表",
    description=(
        "返回当前可购买的套餐，按运营配置的顺序排列。不需要登录。"
        "只包含已上架且在销售时间窗口内的套餐；权益里没有的项为 0。价格和权益以此接口为准，不要写死在前端。"
    ),
    response_model=list[PlanOut],
    response_description="在售套餐列表",
)
def list_plans(db: DB):
    return service.list_plans(db)


@router.post(
    "/orders",
    operation_id="orders_create",
    summary="下单",
    description=(
        "为当前用户创建一个待支付订单并返回拉起支付的参数。需要登录。"
        "照片范围为“单张”的套餐必须传 photo_id（本人的照片）；加购项必须传 parent_entitlement_id（本人有效的权益）。"
        "订单 30 分钟内有效。支持 Idempotency-Key：网络重试时带同一个 key，只会创建一个订单。"
    ),
    response_model=OrderCreatedOut,
    response_description="订单信息和拉起支付的参数 pay_params",
    responses=errors_doc(
        *_AUTH,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.PLAN_NOT_AVAILABLE,
        ErrorCode.PHOTO_NOT_FOUND,
        ErrorCode.ENTITLEMENT_NOT_FOUND,
        ErrorCode.ENTITLEMENT_EXPIRED,
        ErrorCode.IDEMPOTENCY_CONFLICT,
        ErrorCode.ORDER_NOT_PAYABLE,
        ErrorCode.INTERNAL_ERROR,
    ),
)
def create_order(payload: OrderCreateIn, me: Me, db: DB, idem: IdempotencyKeyHeader = None):
    return service.create_order(db, me.id, idem, payload)


@router.get(
    "/orders",
    operation_id="orders_list",
    summary="我的订单列表",
    description=(
        "返回当前用户的订单，按下单时间从新到旧，游标分页。需要登录。"
        "待支付但已超过支付截止时间的订单，读取时会被自动改为已关闭。"
    ),
    response_model=OrderPage,
    response_description="订单分页列表",
    responses=errors_doc(*_AUTH),
)
def list_orders(me: Me, db: DB, page: Page):
    return service.list_orders(db, me.id, page.cursor, page.limit)


@router.get(
    "/orders/{order_no}",
    operation_id="orders_detail",
    summary="订单详情",
    description=(
        "按订单号查询当前用户的订单，支付后前端用它确认订单是否已变为 paid。需要登录。"
        "真实支付模式下，查询待支付订单时会向微信确认支付结果。"
        "别人的订单或不存在的订单号都返回 ORDER_NOT_FOUND。待支付但已超时的订单会被自动改为已关闭。"
    ),
    response_model=OrderOut,
    response_description="订单详情",
    responses=errors_doc(
        *_AUTH, ErrorCode.ORDER_NOT_FOUND, ErrorCode.ORDER_NOT_PAYABLE, ErrorCode.INTERNAL_ERROR
    ),
)
def get_order(order_no: OrderNoPath, me: Me, db: DB):
    return service.get_order(db, me.id, order_no)


@router.post(
    "/orders/{order_no}/cancel",
    operation_id="orders_cancel",
    summary="取消订单",
    description=(
        "取消当前用户的待支付订单。需要登录。真实支付模式下先在微信关单，再将本地订单改为已关闭。"
        "已支付或已关闭的订单返回 ORDER_NOT_CANCELLABLE，微信关单暂未确认时可以重试。"
    ),
    response_model=OrderOut,
    response_description="取消后的订单",
    responses=errors_doc(
        *_AUTH, ErrorCode.ORDER_NOT_FOUND, ErrorCode.ORDER_NOT_CANCELLABLE, ErrorCode.INTERNAL_ERROR
    ),
)
def cancel_order(order_no: OrderNoPath, me: Me, db: DB):
    return service.cancel_order(db, me.id, order_no)


# ---------- 支付回调 ----------


async def _raw_body(request: Request) -> bytes:
    return await request.body()


_WX_ACK = (
    "回调使用微信支付协议。成功返回 HTTP 204 空响应。"
    '失败固定返回 {"code":"FAIL","message":"失败原因"}，各状态码对应的内部错误仅供排查。'
)


def _wxpay_errors(*codes: ErrorCode) -> dict:
    return {
        status: {"model": WxpayFailure, "description": response["description"]}
        for status, response in errors_doc(*codes, ErrorCode.INTERNAL_ERROR).items()
    }


def _wxpay_ack(
    handler: Callable[[Session, Mapping[str, str], bytes], None], db: Session, request: Request, body: bytes
) -> Response:
    try:
        handler(db, request.headers, body)
    except Exception as exc:
        if not isinstance(exc, AppError):
            log.error("微信支付回调处理失败 handler=%s error_type=%s", handler.__name__, type(exc).__name__)
            exc = AppError(ErrorCode.INTERNAL_ERROR)
        db.rollback()
        return JSONResponse(
            status_code=exc.status, content=WxpayFailure(code="FAIL", message=exc.message).model_dump()
        )
    return Response(status_code=204)


@callback_router.post(
    "/wxpay",
    operation_id="callbacks_wxpay",
    summary="微信支付结果通知",
    description=(
        "由微信支付服务器调用，无需登录。服务端验证签名并解密原始报文。重复通知不会重复发放权益。"
        "订单已关闭时自动发起全额退款，保留系统退款记录，不发放权益。"
        "联调（fake）模式下，签名放在 X-Fake-Signature 请求头，请求体是 JSON。" + _WX_ACK
    ),
    status_code=204,
    response_class=Response,
    response_description="通知已处理",
    responses=_wxpay_errors(
        ErrorCode.PAYMENT_SIGNATURE_INVALID,
        ErrorCode.ORDER_NOT_FOUND,
        ErrorCode.ORDER_NOT_PAYABLE,
        ErrorCode.VALIDATION_ERROR,
    ),
)
def wxpay_notify(request: Request, db: DB, body: Annotated[bytes, Depends(_raw_body)]):
    return _wxpay_ack(service.handle_wxpay_notify, db, request, body)


@callback_router.post(
    "/wxpay/refund",
    operation_id="callbacks_wxpay_refund",
    summary="微信退款结果通知",
    description=(
        "由微信支付服务器调用，无需登录。验签解密后核对商户单号、微信支付单号和金额。"
        "成功退款入账一次，退款关闭释放预占余额。退款异常继续预占，等待商户处理。" + _WX_ACK
    ),
    status_code=204,
    response_class=Response,
    response_description="退款通知已处理",
    responses=_wxpay_errors(
        ErrorCode.PAYMENT_SIGNATURE_INVALID,
        ErrorCode.NOT_FOUND,
        ErrorCode.REFUND_NOT_ALLOWED,
        ErrorCode.VALIDATION_ERROR,
    ),
)
def wxpay_refund_notify(request: Request, db: DB, body: Annotated[bytes, Depends(_raw_body)]):
    return _wxpay_ack(service.handle_wxpay_refund_notify, db, request, body)


# ---------- 联调 ----------


@dev_router.post(
    "/orders/{order_no}/simulate-paid",
    operation_id="dev_orders_simulate_paid",
    summary="模拟支付成功（仅开发测试）",
    description=(
        "联调用，生产环境不存在此接口。需要登录，且只能操作自己的订单。"
        "效果等同于收到一笔支付成功的通知：订单变为已支付并发放权益。重复调用不会重复发放。"
        "下单返回 pay_params.mode=fake 时，前端改调这个接口代替微信支付。"
    ),
    response_model=OrderOut,
    response_description="支付后的订单",
    responses=errors_doc(*_AUTH, ErrorCode.ORDER_NOT_FOUND, ErrorCode.ORDER_NOT_PAYABLE),
)
def simulate_paid(order_no: OrderNoPath, me: Me, db: DB):
    return service.simulate_paid(db, me.id, order_no)
