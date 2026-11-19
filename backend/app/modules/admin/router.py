from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Path, Query, Request, Response

from app.core.config import settings
from app.core.deps import DB, Admin, CurrentAdmin, Page, require
from app.core.errors import ErrorCode, errors_doc
from app.core.schemas import OkResponse
from app.modules.admin import service
from app.modules.admin.schemas import (
    AdminApplicationDetail,
    AdminApplicationPage,
    AdminAuditLogPage,
    AdminLoginIn,
    AdminLoginOut,
    AdminMeOut,
    AdminOrderDetail,
    AdminOrderPage,
    AdminPlanCreateIn,
    AdminPlanOut,
    AdminPlanUpdateIn,
    AdminProviderOut,
    AdminProviderUpdateIn,
    AdminRefundIn,
    AdminRefundResultOut,
    AdminSpecCreateIn,
    AdminSpecOut,
    AdminSpecPage,
    AdminSpecUpdateIn,
    AdminUserDetail,
    AdminUserPage,
)

admin_router = APIRouter(tags=["后台"])

COOKIE_NAME = "admin_session"
COOKIE_PATH = "/api/v1/admin"

_AUTH = (ErrorCode.AUTH_REQUIRED, ErrorCode.AUTH_INVALID, ErrorCode.PERMISSION_DENIED)
_LOGIN_NOTE = "需要后台登录（Cookie）；没有对应权限点返回 PERMISSION_DENIED。"
_WRITE_NOTE = "修改类请求必须带请求头 X-CSRF-Token（登录时返回的 csrf_token），缺少或错误返回 PERMISSION_DENIED。操作会写入审计日志。"


def _perm(point: str):
    return Annotated[CurrentAdmin, Depends(require(point))]


UserRead = _perm("user:read")
OrderRead = _perm("order:read")
RefundCreate = _perm("refund:create")
ApplicationRead = _perm("application:read")
ApplicationOperate = _perm("application:operate")
PlanRead = _perm("plan:read")
PlanWrite = _perm("plan:write")
SpecRead = _perm("spec:read")
SpecWrite = _perm("spec:write")
ProviderRead = _perm("provider:read")
ProviderWrite = _perm("provider:write")
AuditRead = _perm("audit:read")

OrderNoPath = Annotated[str, Path(description="订单号", examples=["O20261119083012A1B2C3"])]
AppNoPath = Annotated[str, Path(description="回执申请单号", examples=["R20261119083012A1B2C3"])]
UserIdPath = Annotated[int, Path(description="用户 ID", ge=1, examples=[1024])]
PlanCodePath = Annotated[str, Path(description="套餐编码", examples=["photo_year_39_9"])]
SpecCodePath = Annotated[str, Path(description="规格编码", examples=["gd_idcard"])]
ProviderCodePath = Annotated[str, Path(description="服务商编码", examples=["zheying"])]

# ---------- 登录 ----------


@admin_router.post(
    "/auth/login",
    operation_id="admin_login",
    summary="后台登录",
    description=(
        "用用户名和密码登录运营后台。不需要登录。成功后服务端通过 httpOnly Cookie（admin_session，仅 /api/v1/admin 路径、"
        "SameSite=Strict）下发会话，并在响应体返回 csrf_token，之后所有修改类请求在请求头 X-CSRF-Token 里带上它。"
        "账号不存在、密码错误、账号被停用都返回同一个 ADMIN_LOGIN_FAILED；同一用户名 15 分钟内失败 5 次后返回 RATE_LIMITED。"
        "会话闲置 2 小时、最长 12 小时失效（以服务端配置为准）。"
    ),
    response_model=AdminLoginOut,
    response_description="登录成功，返回 csrf_token 和账号信息，会话 Cookie 已写入",
    responses=errors_doc(ErrorCode.ADMIN_LOGIN_FAILED, ErrorCode.RATE_LIMITED),
)
def login(body: AdminLoginIn, request: Request, response: Response, db: DB):
    out, token = service.login(
        db,
        username=body.username,
        password=body.password,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="strict",
        secure=settings.is_prod,
        path=COOKIE_PATH,
        max_age=settings.admin_session_absolute_hours * 3600,
    )
    return out


@admin_router.post(
    "/auth/logout",
    operation_id="admin_logout",
    summary="后台退出登录",
    description="吊销当前会话并清除 Cookie。不需要登录态：没有登录、会话已失效也返回成功，可重复调用。",
    response_model=OkResponse,
    response_description="已退出",
)
def logout(
    response: Response,
    db: DB,
    admin_session: Annotated[
        str | None, Cookie(description="后台会话 Cookie，浏览器自动携带；前端不用手动传")
    ] = None,
):
    result = service.logout(db, token=admin_session)
    response.delete_cookie(
        COOKIE_NAME, path=COOKIE_PATH, httponly=True, samesite="strict", secure=settings.is_prod
    )
    return result


@admin_router.get(
    "/me",
    operation_id="admin_me",
    summary="当前后台账号",
    description="返回当前登录的后台账号、角色和全部权限点，前端用权限点决定显示哪些菜单和按钮。需要后台登录。",
    response_model=AdminMeOut,
    response_description="当前账号和权限",
    responses=errors_doc(ErrorCode.AUTH_REQUIRED, ErrorCode.AUTH_INVALID),
)
def get_me(admin: Admin):
    return service.me(admin)


# ---------- 用户 ----------


@admin_router.get(
    "/users",
    operation_id="admin_users_list",
    summary="用户列表",
    description=(
        f"按注册时间从新到旧列出用户，游标分页，条件之间是“并且”。权限点 user:read。{_LOGIN_NOTE}"
        "手机号只返回打码后的；按手机号查询时传明文完整手机号，服务端用哈希匹配。"
    ),
    response_model=AdminUserPage,
    response_description="用户分页列表",
    responses=errors_doc(*_AUTH),
)
def list_users(
    _: UserRead,
    db: DB,
    page: Page,
    user_id: Annotated[int | None, Query(ge=1, description="按用户 ID 精确查找", examples=[1024])] = None,
    phone: Annotated[
        str | None,
        Query(
            min_length=5, max_length=20, description="按完整手机号精确查找（明文）", examples=["13800001234"]
        ),
    ] = None,
    status: Annotated[
        str | None,
        Query(
            pattern="^(active|disabled|cancelled)$",
            description="按账号状态筛选：active = 正常；disabled = 已停用；cancelled = 已注销",
            examples=["active"],
        ),
    ] = None,
):
    return service.list_users(db, user_id=user_id, phone=phone, status=status, page=page)


@admin_router.get(
    "/users/{user_id}",
    operation_id="admin_users_detail",
    summary="用户详情",
    description=f"按用户 ID 查看用户资料、登录身份、订单统计。权限点 user:read。{_LOGIN_NOTE}",
    response_model=AdminUserDetail,
    response_description="用户详情",
    responses=errors_doc(*_AUTH, ErrorCode.NOT_FOUND),
)
def get_user(user_id: UserIdPath, _: UserRead, db: DB):
    return service.get_user(db, user_id)


# ---------- 订单 ----------


@admin_router.get(
    "/orders",
    operation_id="admin_orders_list",
    summary="订单列表",
    description=f"按下单时间从新到旧列出订单，游标分页，条件之间是“并且”。权限点 order:read。{_LOGIN_NOTE}",
    response_model=AdminOrderPage,
    response_description="订单分页列表",
    responses=errors_doc(*_AUTH),
)
def list_orders(
    _: OrderRead,
    db: DB,
    page: Page,
    status: Annotated[
        str | None,
        Query(
            pattern="^(pending|paid|closed|part_refunded|refunded)$",
            description="按订单状态筛选：pending = 待支付；paid = 已支付；closed = 已关闭；part_refunded = 部分退款；refunded = 已全额退款",
            examples=["paid"],
        ),
    ] = None,
    order_no: Annotated[
        str | None, Query(max_length=64, description="按订单号精确查找", examples=["O20261119083012A1B2C3"])
    ] = None,
    user_id: Annotated[int | None, Query(ge=1, description="按下单用户 ID 筛选", examples=[1024])] = None,
    created_from: Annotated[
        datetime | None,
        Query(description="下单时间起点（含），带时区的 ISO 8601", examples=["2026-11-01T00:00:00Z"]),
    ] = None,
    created_to: Annotated[
        datetime | None,
        Query(description="下单时间终点（不含），带时区的 ISO 8601", examples=["2026-12-01T00:00:00Z"]),
    ] = None,
):
    return service.list_orders(
        db,
        status=status,
        order_no=order_no,
        user_id=user_id,
        created_from=created_from,
        created_to=created_to,
        page=page,
    )


@admin_router.get(
    "/orders/{order_no}",
    operation_id="admin_orders_detail",
    summary="订单详情",
    description=f"查看订单的商品项、支付流水和退款记录。权限点 order:read。{_LOGIN_NOTE}",
    response_model=AdminOrderDetail,
    response_description="订单详情",
    responses=errors_doc(*_AUTH, ErrorCode.ORDER_NOT_FOUND),
)
def get_order(order_no: OrderNoPath, _: OrderRead, db: DB):
    return service.get_order(db, order_no)


@admin_router.post(
    "/orders/{order_no}/refunds",
    operation_id="admin_orders_refund",
    summary="订单退款",
    description=(
        f"对已支付或部分退款的订单发起退款，原路退回。权限点 refund:create。{_LOGIN_NOTE}{_WRITE_NOTE}"
        "退款金额必须大于 0 且不超过可退余额（已付 - 已退 - 处理中的退款），否则 REFUND_NOT_ALLOWED。"
        "退完（全额）后订单变 refunded，并撤销该订单发放的权益（用户不能再下载、换规格）；未退完变 part_refunded，权益保留。"
        "没有幂等键，请不要重复点击；重复提交会按剩余可退余额再退一次。"
    ),
    response_model=AdminRefundResultOut,
    response_description="退款记录和退款后的订单状态",
    responses=errors_doc(*_AUTH, ErrorCode.ORDER_NOT_FOUND, ErrorCode.REFUND_NOT_ALLOWED),
)
def refund_order(order_no: OrderNoPath, body: AdminRefundIn, admin: RefundCreate, db: DB):
    return service.refund_order(db, admin, order_no, body)


# ---------- 回执申请 ----------


@admin_router.get(
    "/receipt-applications",
    operation_id="admin_applications_list",
    summary="回执申请列表",
    description=f"按创建时间从新到旧列出回执申请，游标分页，条件之间是“并且”。权限点 application:read。{_LOGIN_NOTE}",
    response_model=AdminApplicationPage,
    response_description="回执申请分页列表",
    responses=errors_doc(*_AUTH),
)
def list_applications(
    _: ApplicationRead,
    db: DB,
    page: Page,
    status: Annotated[
        str | None,
        Query(
            pattern="^(pending|processing|rejected|completed|failed|cancelled)$",
            description="按申请状态筛选：pending = 已创建未提交；processing = 办理中；rejected = 被驳回；completed = 已出回执；failed = 失败；cancelled = 已取消",
            examples=["rejected"],
        ),
    ] = None,
    app_no: Annotated[
        str | None, Query(max_length=64, description="按申请单号精确查找", examples=["R20261119083012A1B2C3"])
    ] = None,
    user_id: Annotated[int | None, Query(ge=1, description="按申请人用户 ID 筛选", examples=[1024])] = None,
    spec_code: Annotated[
        str | None, Query(max_length=64, description="按规格编码筛选", examples=["gd_idcard"])
    ] = None,
):
    return service.list_applications(
        db, status=status, app_no=app_no, user_id=user_id, spec_code=spec_code, page=page
    )


@admin_router.get(
    "/receipt-applications/{app_no}",
    operation_id="admin_applications_detail",
    summary="回执申请详情",
    description=(
        f"查看申请详情，包含全部服务商提交记录（服务商、状态、驳回原因、成本、时间）和打码后的办理表单。权限点 application:read。{_LOGIN_NOTE}"
        "后台看不到姓名、身份证号明文。"
    ),
    response_model=AdminApplicationDetail,
    response_description="回执申请详情",
    responses=errors_doc(*_AUTH, ErrorCode.APPLICATION_NOT_FOUND),
)
def get_application(app_no: AppNoPath, _: ApplicationRead, db: DB):
    return service.get_application(db, app_no)


@admin_router.post(
    "/receipt-applications/{app_no}/cancel",
    operation_id="admin_applications_cancel",
    summary="取消回执申请",
    description=(
        f"代用户取消回执申请并退还回执次数。权限点 application:operate。{_LOGIN_NOTE}{_WRITE_NOTE}"
        "只有 pending（未提交）和 rejected（被驳回）的申请可以取消，其他状态返回 APPLICATION_NOT_RESUBMITTABLE。"
    ),
    response_model=AdminApplicationDetail,
    response_description="取消后的申请详情",
    responses=errors_doc(*_AUTH, ErrorCode.APPLICATION_NOT_FOUND, ErrorCode.APPLICATION_NOT_RESUBMITTABLE),
)
def cancel_application(app_no: AppNoPath, admin: ApplicationOperate, db: DB):
    return service.cancel_application(db, admin, app_no)


# ---------- 套餐 ----------


@admin_router.get(
    "/plans",
    operation_id="admin_plans_list",
    summary="套餐列表",
    description=f"列出全部套餐（含草稿、已下架）及其权益配置，数量少所以不分页。权限点 plan:read。{_LOGIN_NOTE}",
    response_model=list[AdminPlanOut],
    response_description="全部套餐",
    responses=errors_doc(*_AUTH),
)
def list_plans(_: PlanRead, db: DB):
    return service.list_plans(db)


@admin_router.post(
    "/plans",
    operation_id="admin_plans_create",
    summary="创建套餐",
    description=(
        f"创建一个套餐及其权益。权限点 plan:write（仅 owner）。{_LOGIN_NOTE}{_WRITE_NOTE}"
        "权益类型必须是系统支持的类型，套餐编码不能重复，否则返回 VALIDATION_ERROR。"
    ),
    response_model=AdminPlanOut,
    response_description="创建后的套餐",
    responses=errors_doc(*_AUTH, ErrorCode.VALIDATION_ERROR),
)
def create_plan(body: AdminPlanCreateIn, admin: PlanWrite, db: DB):
    return service.create_plan(db, admin, body)


@admin_router.patch(
    "/plans/{code}",
    operation_id="admin_plans_update",
    summary="修改套餐",
    description=(
        f"修改套餐的名称、价格、状态、排序、销售时间、展示配置、权益。权限点 plan:write（仅 owner）。{_LOGIN_NOTE}{_WRITE_NOTE}"
        "只改传了的字段；传 benefits 表示整体替换权益。已售出的权益使用购买时的快照，修改套餐不影响已买的用户。"
    ),
    response_model=AdminPlanOut,
    response_description="修改后的套餐",
    responses=errors_doc(*_AUTH, ErrorCode.NOT_FOUND, ErrorCode.VALIDATION_ERROR),
)
def update_plan(code: PlanCodePath, body: AdminPlanUpdateIn, admin: PlanWrite, db: DB):
    return service.update_plan(db, admin, code, body)


# ---------- 规格 ----------


@admin_router.get(
    "/specs",
    operation_id="admin_specs_list",
    summary="规格列表",
    description=f"列出全部规格（含已下架），按创建时间从新到旧，游标分页。权限点 spec:read。{_LOGIN_NOTE}",
    response_model=AdminSpecPage,
    response_description="规格分页列表",
    responses=errors_doc(*_AUTH),
)
def list_specs(_: SpecRead, db: DB, page: Page):
    return service.list_specs(db, page)


@admin_router.post(
    "/specs",
    operation_id="admin_specs_create",
    summary="创建规格",
    description=(
        f"创建一个证件照规格。权限点 spec:write。{_LOGIN_NOTE}{_WRITE_NOTE}"
        "规格编码不能重复，父规格必须已存在，否则返回 VALIDATION_ERROR。"
    ),
    response_model=AdminSpecOut,
    response_description="创建后的规格",
    responses=errors_doc(*_AUTH, ErrorCode.VALIDATION_ERROR),
)
def create_spec(body: AdminSpecCreateIn, admin: SpecWrite, db: DB):
    return service.create_spec(db, admin, body)


@admin_router.patch(
    "/specs/{code}",
    operation_id="admin_specs_update",
    summary="修改规格",
    description=(
        f"修改规格的名称、尺寸、底色、办理表单、状态等；下架用 status=inactive。权限点 spec:write。{_LOGIN_NOTE}{_WRITE_NOTE}"
        "只改传了的字段；编码和父规格不可改。"
    ),
    response_model=AdminSpecOut,
    response_description="修改后的规格",
    responses=errors_doc(*_AUTH, ErrorCode.NOT_FOUND, ErrorCode.VALIDATION_ERROR),
)
def update_spec(code: SpecCodePath, body: AdminSpecUpdateIn, admin: SpecWrite, db: DB):
    return service.update_spec(db, admin, code, body)


# ---------- 服务商 ----------


@admin_router.get(
    "/providers",
    operation_id="admin_providers_list",
    summary="服务商列表",
    description=f"列出回执服务商及其能办理的规格、路由规则，不返回密钥。数量少所以不分页。权限点 provider:read。{_LOGIN_NOTE}",
    response_model=list[AdminProviderOut],
    response_description="全部服务商",
    responses=errors_doc(*_AUTH),
)
def list_providers(_: ProviderRead, db: DB):
    return service.list_providers(db)


@admin_router.patch(
    "/providers/{code}",
    operation_id="admin_providers_update",
    summary="修改服务商状态",
    description=(
        f"启用、停用或手动熔断一个服务商，路由会跳过非 enabled 的服务商。权限点 provider:write（仅 owner）。{_LOGIN_NOTE}{_WRITE_NOTE}"
    ),
    response_model=AdminProviderOut,
    response_description="修改后的服务商",
    responses=errors_doc(*_AUTH, ErrorCode.NOT_FOUND),
)
def update_provider(code: ProviderCodePath, body: AdminProviderUpdateIn, admin: ProviderWrite, db: DB):
    return service.update_provider(db, admin, code, body)


# ---------- 审计日志 ----------


@admin_router.get(
    "/audit-logs",
    operation_id="admin_audit_logs",
    summary="审计日志",
    description=f"按时间从新到旧列出后台操作记录，游标分页。权限点 audit:read。{_LOGIN_NOTE}",
    response_model=AdminAuditLogPage,
    response_description="审计日志分页列表",
    responses=errors_doc(*_AUTH),
)
def list_audit_logs(
    _: AuditRead,
    db: DB,
    page: Page,
    admin_id: Annotated[int | None, Query(ge=1, description="按操作人后台账号 ID 筛选", examples=[3])] = None,
    action: Annotated[
        str | None,
        Query(max_length=64, description="按操作类型筛选，如 refund.create", examples=["refund.create"]),
    ] = None,
    target_type: Annotated[
        str | None, Query(max_length=64, description="按操作对象类型筛选，如 order、plan", examples=["order"])
    ] = None,
):
    return service.list_audit_logs(db, admin_id=admin_id, action=action, target_type=target_type, page=page)
