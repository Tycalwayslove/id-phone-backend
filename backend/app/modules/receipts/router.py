import logging
from typing import Annotated

from fastapi import APIRouter, Body, Path, Query, Request
from starlette.concurrency import run_in_threadpool

from app.core.deps import DB, IdempotencyKeyHeader, Me, Page
from app.core.errors import ErrorCode, errors_doc
from app.core.schemas import OkResponse
from app.modules.receipts import service
from app.modules.receipts.schemas import (
    ApplicationOut,
    ApplicationPage,
    ReceiptCreate,
    ReceiptProviderAck,
    ResubmitRequest,
    SimulateRequest,
)

router = APIRouter(tags=["回执"])
callback_router = APIRouter(tags=["回调"])
dev_router = APIRouter(tags=["联调"])

_AUTH = (ErrorCode.AUTH_REQUIRED, ErrorCode.AUTH_INVALID, ErrorCode.ACCOUNT_DISABLED)


class _ReceiptAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn 访问日志第 3 个参数为路径及查询串。
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            path = args[2].partition("?")[0]
            if path.startswith("/api/v1/callbacks/receipt/"):
                record.args = (*args[:2], path, *args[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(_ReceiptAccessLogFilter())


AppNo = Annotated[
    str,
    Path(
        max_length=64,
        description="回执申请单号，来自创建申请或列表接口的 app_no",
        examples=["R20261119083012A1B2C3"],
    ),
]


@router.post(
    "/receipt-applications",
    operation_id="receipts_create",
    summary="创建回执申请",
    description=(
        "为一张照片办理官方照片回执。需要登录。"
        "系统按规格和地区自动选择服务商，校验办理表单，占用一次回执次数并提交办理，申请进入“办理中”。"
        "办理结果通过服务商回调或系统轮询得到，用户可通过详情接口查看。"
        "支持 Idempotency-Key 请求头防止重复提交。"
        "一卡一人的权益会在第一次办理时绑定身份证号，之后只能为同一人办理。"
    ),
    response_model=ApplicationOut,
    response_description="创建后的申请，通常处于办理中（processing）；提交服务商失败时为 failed",
    responses=errors_doc(
        *_AUTH,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.IDEMPOTENCY_CONFLICT,
        ErrorCode.SPEC_NOT_FOUND,
        ErrorCode.PHOTO_NOT_FOUND,
        ErrorCode.PHOTO_ACCESS_EXPIRED,
        ErrorCode.PHOTO_NOT_READY,
        ErrorCode.PHOTO_REJECTED,
        ErrorCode.RECEIPT_NOT_SUPPORTED,
        ErrorCode.PROVIDER_UNAVAILABLE,
        ErrorCode.ENTITLEMENT_EXPIRED,
        ErrorCode.QUOTA_EXHAUSTED,
        ErrorCode.ONE_PERSON_MISMATCH,
    ),
)
def receipts_create(body: ReceiptCreate, me: Me, db: DB, idem: IdempotencyKeyHeader = None):
    return service.create_application(db, user_id=me.id, idem_key=idem, payload=body)


@router.get(
    "/receipt-applications",
    operation_id="receipts_list",
    summary="我的回执申请列表",
    description="分页列出当前用户的回执申请，按创建时间从新到旧。需要登录。只能看到自己的申请。",
    response_model=ApplicationPage,
    response_description="本页申请和下一页游标",
    responses=errors_doc(*_AUTH),
)
def receipts_list(me: Me, db: DB, page: Page):
    return service.list_applications(db, user_id=me.id, page=page)


@router.get(
    "/receipt-applications/{app_no}",
    operation_id="receipts_detail",
    summary="回执申请详情",
    description=(
        "查看一条回执申请的状态、驳回原因、还能重提几次、回执图片链接和每次提交记录。需要登录。"
        "别人的申请和不存在的申请一样返回 APPLICATION_NOT_FOUND。"
    ),
    response_model=ApplicationOut,
    response_description="申请详情",
    responses=errors_doc(*_AUTH, ErrorCode.APPLICATION_NOT_FOUND),
)
def receipts_detail(app_no: AppNo, me: Me, db: DB):
    return service.get_application_detail(db, user_id=me.id, app_no=app_no)


@router.post(
    "/receipt-applications/{app_no}/resubmit",
    operation_id="receipts_resubmit",
    summary="驳回后重新提交",
    description=(
        "被驳回（rejected）的申请可以重新提交，可换一张新照片。需要登录。"
        "不会再次占用回执次数；重提次数受权益限制，用完后返回 RESUBMIT_LIMIT_REACHED；"
        "权益已过期返回 ENTITLEMENT_EXPIRED。支持 Idempotency-Key 请求头防止重复提交。"
    ),
    response_model=ApplicationOut,
    response_description="重提后的申请，状态变为办理中（processing）",
    responses=errors_doc(
        *_AUTH,
        ErrorCode.IDEMPOTENCY_CONFLICT,
        ErrorCode.APPLICATION_NOT_FOUND,
        ErrorCode.APPLICATION_NOT_RESUBMITTABLE,
        ErrorCode.RESUBMIT_LIMIT_REACHED,
        ErrorCode.ENTITLEMENT_EXPIRED,
        ErrorCode.PHOTO_NOT_FOUND,
        ErrorCode.PHOTO_ACCESS_EXPIRED,
        ErrorCode.PHOTO_NOT_READY,
        ErrorCode.PHOTO_REJECTED,
        ErrorCode.RECEIPT_NOT_SUPPORTED,
        ErrorCode.PROVIDER_UNAVAILABLE,
    ),
)
def receipts_resubmit(
    app_no: AppNo,
    me: Me,
    db: DB,
    body: Annotated[ResubmitRequest, Body()] = ResubmitRequest(),
    idem: IdempotencyKeyHeader = None,
):
    return service.resubmit_application(db, user_id=me.id, idem_key=idem, app_no=app_no, payload=body)


@router.post(
    "/receipt-applications/{app_no}/cancel",
    operation_id="receipts_cancel",
    summary="取消回执申请",
    description=(
        "取消申请并退还占用的回执次数。需要登录。只有“已创建”（pending）和“被驳回”（rejected）的申请能取消，"
        "办理中、已出回执、已失败的申请不能取消。"
    ),
    response_model=ApplicationOut,
    response_description="取消后的申请，状态为 cancelled",
    responses=errors_doc(*_AUTH, ErrorCode.APPLICATION_NOT_FOUND, ErrorCode.APPLICATION_NOT_RESUBMITTABLE),
)
def receipts_cancel(app_no: AppNo, me: Me, db: DB):
    return service.cancel_application_out(db, user_id=me.id, app_no=app_no)


@callback_router.post(
    "/receipt/{provider_code}",
    operation_id="callbacks_receipt_provider",
    summary="回执服务商回调",
    description=(
        "供回执服务商推送办理结果，无需登录。鹧应和黔微云提交表单，系统验证签名、nonce 和单号归属，"
        "配置来源白名单时也检查来源 IP。校验失败返回 CALLBACK_SIGNATURE_INVALID。"
        "同一单号的同一状态只处理一次，重复通知仍返回成功。"
    ),
    response_model=OkResponse | ReceiptProviderAck,
    response_description="回调已处理（含重复回调）。真实通道返回同步完成，假通道返回 ok",
    responses=errors_doc(
        ErrorCode.CALLBACK_SIGNATURE_INVALID,
        ErrorCode.NOT_FOUND,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.PROVIDER_UNAVAILABLE,
    ),
)
async def callbacks_receipt_provider(
    request: Request,
    db: DB,
    provider_code: Annotated[
        str, Path(max_length=64, description="服务商编码，对应后台配置的服务商 code", examples=["zheying"])
    ],
    nonce: Annotated[
        str | None,
        Query(description="提交时生成的回调校验串，真实通道必填", examples=["example-callback-nonce"]),
    ] = None,
):
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    return await run_in_threadpool(
        service.handle_callback,
        db,
        provider_code=provider_code,
        headers=headers,
        body=body,
        nonce=nonce if len(request.query_params.getlist("nonce")) == 1 else None,
        source_ip=request.client.host if request.client else None,
    )


@dev_router.post(
    "/receipt-applications/{app_no}/simulate",
    operation_id="dev_receipts_simulate",
    summary="模拟回执结果（联调）",
    description=(
        "仅开发和测试环境可用，生产环境不开放。需要登录，只能操作自己的申请。"
        "让假通道对该申请当前一次提交给出指定结果（成功、驳回或失败），并像真实回调一样更新申请。"
        "非假通道模式下返回 NOT_FOUND。"
    ),
    response_model=ApplicationOut,
    response_description="模拟后的申请",
    responses=errors_doc(*_AUTH, ErrorCode.APPLICATION_NOT_FOUND, ErrorCode.NOT_FOUND),
)
def dev_receipts_simulate(app_no: AppNo, body: SimulateRequest, me: Me, db: DB):
    return service.simulate_result(db, user_id=me.id, app_no=app_no, payload=body)
