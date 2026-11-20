from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Path, Query, Request, Response

from app.core.config import settings
from app.core.deps import DB, Admin, CurrentAdmin, Page, require
from app.core.errors import ErrorCode, errors_doc
from app.core.pagination import PageParams
from app.core.schemas import OkResponse
from app.modules.admin import service
from app.modules.admin.schemas import (
    NOTIFY_STATUS_DOC,
    AdminAccountCreateIn,
    AdminAccountOut,
    AdminAccountPage,
    AdminAccountRoleIn,
    AdminApplicationDetail,
    AdminApplicationPage,
    AdminAuditLogPage,
    AdminLoginIn,
    AdminLoginOut,
    AdminManualReviewIn,
    AdminMeOut,
    AdminNotifyTaskPage,
    AdminOrderDetail,
    AdminOrderPage,
    AdminPasswordResetOut,
    AdminPlanCreateIn,
    AdminPlanOut,
    AdminPlanUpdateIn,
    AdminProviderOut,
    AdminProviderSpecCreateIn,
    AdminProviderSpecOut,
    AdminProviderSpecPage,
    AdminProviderSpecUpdateIn,
    AdminProviderUpdateIn,
    AdminRefundIn,
    AdminRefundResultOut,
    AdminRouteRuleCreateIn,
    AdminRouteRuleOut,
    AdminRouteRulePage,
    AdminRouteRuleUpdateIn,
    AdminSpecCreateIn,
    AdminSpecOut,
    AdminSpecPage,
    AdminSpecRegionOut,
    AdminSpecUpdateIn,
    AdminStatsOverviewOut,
    AdminUserDetail,
    AdminUserPage,
    AdminUserSearchIn,
    NotifyStatus,
    SpecCategory,
    SpecStatus,
)
from app.modules.specs.schemas import ProviderSyncResult

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
StatsRead = _perm("stats:read")
NotifyRead = _perm("notify:read")
AdminAccountRead = _perm("admin:read")
AdminAccountWrite = _perm("admin:write")

OrderNoPath = Annotated[str, Path(description="订单号", examples=["O20261119083012A1B2C3"])]
AppNoPath = Annotated[str, Path(description="回执申请单号", examples=["R20261119083012A1B2C3"])]
UserIdPath = Annotated[int, Path(description="用户 ID", ge=1, examples=[1024])]
PlanCodePath = Annotated[str, Path(description="套餐编码", examples=["photo_year_39_9"])]
SpecCodePath = Annotated[str, Path(description="规格编码", examples=["gd_idcard"])]
ProviderCodePath = Annotated[str, Path(description="服务商编码", examples=["zheying"])]
AdminIdPath = Annotated[int, Path(ge=1, le=2**63 - 1, description="管理员账号 ID", examples=[3])]
ProviderSpecIdPath = Annotated[int, Path(ge=1, le=2**63 - 1, description="服务商规格记录 ID", examples=[71])]
RouteRuleIdPath = Annotated[int, Path(ge=1, le=2**63 - 1, description="路由规则 ID", examples=[86])]

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
        "使用重置获得的临时密码登录时，必须同时提供不同的 new_password。登录成功后临时密码失效。"
    ),
    response_model=AdminLoginOut,
    response_description="登录成功，返回 csrf_token 和账号信息，会话 Cookie 已写入",
    responses=errors_doc(ErrorCode.ADMIN_LOGIN_FAILED, ErrorCode.RATE_LIMITED, ErrorCode.VALIDATION_ERROR),
)
def login(body: AdminLoginIn, request: Request, response: Response, db: DB):
    out, token = service.login(
        db,
        username=body.username,
        password=body.password,
        new_password=body.new_password,
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
        "手机号只返回打码后的；按手机号筛选请调用 POST /api/v1/admin/users/search。"
    ),
    response_model=AdminUserPage,
    response_description="用户分页列表",
    responses=errors_doc(*_AUTH, ErrorCode.VALIDATION_ERROR),
)
def list_users(
    _: UserRead,
    db: DB,
    page: Page,
    user_id: Annotated[int | None, Query(ge=1, description="按用户 ID 精确查找", examples=[1024])] = None,
    status: Annotated[
        str | None,
        Query(
            pattern="^(active|disabled|cancelled)$",
            description="按账号状态筛选：active = 正常；disabled = 已停用；cancelled = 已注销",
            examples=["active"],
        ),
    ] = None,
):
    return service.list_users(db, user_id=user_id, status=status, page=page)


@admin_router.post(
    "/users/search",
    operation_id="admin_users_search",
    summary="按条件查询用户",
    description=(
        f"按注册时间从新到旧查询用户，游标分页，条件之间是“并且”。权限点 user:read。{_LOGIN_NOTE}"
        "请求头需带登录时返回的 X-CSRF-Token。按手机号筛选时在请求体传完整手机号，"
        "服务端用哈希匹配，响应仅返回打码后的手机号。"
    ),
    response_model=AdminUserPage,
    response_description="符合条件的用户分页列表",
    responses=errors_doc(*_AUTH, ErrorCode.VALIDATION_ERROR),
)
def search_users(body: AdminUserSearchIn, _: UserRead, db: DB):
    return service.list_users(
        db,
        user_id=body.user_id,
        status=body.status,
        page=PageParams.of(body),
        phone=body.phone,
    )


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
        "渠道返回处理中时占用可退余额，等待渠道确认。退款成功后更新订单金额；全额退完时撤销订单及附属加购权益，并取消未办结的回执申请。"
        "重试时复用 request_id：相同订单和金额返回原退款记录，订单或金额不同返回 IDEMPOTENCY_CONFLICT。"
    ),
    response_model=AdminRefundResultOut,
    response_description="退款记录和退款后的订单状态",
    responses=errors_doc(
        *_AUTH,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.ORDER_NOT_FOUND,
        ErrorCode.REFUND_NOT_ALLOWED,
        ErrorCode.IDEMPOTENCY_CONFLICT,
        ErrorCode.INTERNAL_ERROR,
    ),
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
    responses=errors_doc(*_AUTH, ErrorCode.VALIDATION_ERROR),
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
    manual_review: Annotated[
        bool | None,
        Query(
            description="按人工核对标记筛选。true 仅查需人工核对，false 仅查无需人工核对，省略则全部",
            examples=[True],
        ),
    ] = None,
):
    return service.list_applications(
        db,
        status=status,
        app_no=app_no,
        user_id=user_id,
        spec_code=spec_code,
        manual_review=manual_review,
        page=page,
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


@admin_router.post(
    "/receipt-applications/{app_no}/manual-review",
    operation_id="admin_applications_manual_review",
    summary="标记回执申请已核对",
    description=(
        f"为需人工核对的申请登记结论，按回执状态机更新申请和当前提交。权限点 application:operate。{_LOGIN_NOTE}{_WRITE_NOTE}"
        "待核对状态已变化时返回 CONFLICT。选择 completed 仅登记已出回执结论。"
    ),
    response_model=AdminApplicationDetail,
    response_description="核对后的申请详情",
    responses=errors_doc(
        *_AUTH, ErrorCode.APPLICATION_NOT_FOUND, ErrorCode.CONFLICT, ErrorCode.VALIDATION_ERROR
    ),
)
def resolve_manual_review(app_no: AppNoPath, admin: ApplicationOperate, db: DB, payload: AdminManualReviewIn):
    return service.resolve_manual_review(db, admin, app_no, payload)


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
        "套餐编码重复返回 CONFLICT，权益类型必须是系统支持的类型。"
    ),
    response_model=AdminPlanOut,
    response_description="创建后的套餐",
    responses=errors_doc(*_AUTH, ErrorCode.VALIDATION_ERROR, ErrorCode.CONFLICT),
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
    description=(
        f"列出全部规格（含已下架），按创建时间从新到旧，游标分页，条件之间是“并且”。权限点 spec:read。{_LOGIN_NOTE}"
        "可按名称、状态、分类和精确的地区码筛选。"
    ),
    response_model=AdminSpecPage,
    response_description="规格分页列表",
    responses=errors_doc(*_AUTH),
)
def list_specs(
    _: SpecRead,
    db: DB,
    page: Page,
    keyword: Annotated[
        str | None,
        Query(
            max_length=64,
            description="按规格名称或编码模糊查找（包含即可，不区分大小写）",
            examples=["身份证"],
        ),
    ] = None,
    status: Annotated[
        SpecStatus | None,
        Query(
            description="按状态筛选：active = 上架；inactive = 下架（含同步进来待审核的）",
            examples=["inactive"],
        ),
    ] = None,
    category: Annotated[
        SpecCategory | None,
        Query(
            description="按分类筛选：receipt = 回执类；normal = 普通证件照；exam = 考试报名照",
            examples=["receipt"],
        ),
    ] = None,
    region_code: Annotated[
        str | None,
        Query(min_length=1, max_length=12, description="按规格保存的地区码精确匹配", examples=["440100"]),
    ] = None,
):
    return service.list_specs(
        db, keyword=keyword, status=status, category=category, page=page, region_code=region_code
    )


@admin_router.get(
    "/spec-regions/{region_code}",
    operation_id="admin_spec_regions_detail",
    summary="查询规格地区名",
    description=f"查询省或市行政区划全称，供规格编辑时预览。权限点 spec:read。{_LOGIN_NOTE}",
    response_model=AdminSpecRegionOut,
    response_description="区划全称查询结果",
    responses=errors_doc(*_AUTH),
)
def get_spec_region(
    _: SpecRead,
    region_code: Annotated[
        str,
        Path(pattern=r"^[0-9]{6}$", description="6 位省或市行政区划码", examples=["440100"]),
    ],
):
    return service.get_spec_region(region_code)


@admin_router.post(
    "/specs",
    operation_id="admin_specs_create",
    summary="创建规格",
    description=(
        f"创建一个证件照规格。权限点 spec:write。{_LOGIN_NOTE}{_WRITE_NOTE}"
        "规格编码重复返回 CONFLICT，父规格必须已存在，否则返回 VALIDATION_ERROR。"
    ),
    response_model=AdminSpecOut,
    response_description="创建后的规格",
    responses=errors_doc(*_AUTH, ErrorCode.VALIDATION_ERROR, ErrorCode.CONFLICT),
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
    description=(
        f"列出全部回执服务商（只有几家，所以不分页），不返回密钥。权限点 provider:read。{_LOGIN_NOTE}"
        "只返回规格映射和路由规则的数量；明细分别用 GET /admin/provider-specs、GET /admin/route-rules 分页查询。"
    ),
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


@admin_router.post(
    "/providers/{code}/sync-specs",
    operation_id="admin_providers_sync_specs",
    summary="同步服务商规格目录",
    description=(
        f"读取服务商的全量规格目录。权限点 provider:write（仅 owner）。{_LOGIN_NOTE}{_WRITE_NOTE}"
        "按上游编号或名称和像素尺寸合并目录。默认上架新规格、启用新映射并创建默认路由规则。"
        "已有规格仅更新制照参数，目录移除的条目会停用映射。目录读取失败时不写入规格变更。"
    ),
    response_model=ProviderSyncResult,
    response_description="新增、更新、未变、停用数量及逐条明细",
    responses=errors_doc(*_AUTH, ErrorCode.NOT_FOUND, ErrorCode.PROVIDER_UNAVAILABLE),
)
def sync_provider_specs(
    code: ProviderCodePath,
    admin: ProviderWrite,
    db: DB,
    auto_publish: Annotated[
        bool,
        Query(
            description=(
                "是否上架新规格、启用新映射并创建默认路由规则。回执类规格且服务商未标记为不可办理时启用规则。"
                "false 时新规格下架、新映射停用且不创建规则。"
            ),
            examples=[True],
        ),
    ] = True,
):
    return service.sync_provider_specs(db, admin, code, auto_publish=auto_publish)


# ---------- 服务商规格与路由规则 ----------


@admin_router.get(
    "/provider-specs",
    operation_id="admin_provider_specs_list",
    summary="服务商规格列表",
    description=(
        f"分页列出服务商规格映射（哪家服务商能办哪个规格、对方规格 ID、成本），按创建时间从新到旧，"
        f"条件之间是“并且”。权限点 provider:read。{_LOGIN_NOTE}"
        "同步规格目录后新增的映射默认停用，可用 is_enabled=false 筛出来逐个配置成本后启用。"
    ),
    response_model=AdminProviderSpecPage,
    response_description="服务商规格映射分页列表",
    responses=errors_doc(*_AUTH),
)
def list_provider_specs(
    _: ProviderRead,
    db: DB,
    page: Page,
    provider_code: Annotated[
        str | None,
        Query(max_length=64, description="按服务商编码筛选；不存在的编码返回空列表", examples=["zheying"]),
    ] = None,
    keyword: Annotated[
        str | None,
        Query(
            max_length=64,
            description="按规格名称、规格编码或服务商规格 ID 模糊查找（包含即可，不区分大小写）",
            examples=["身份证"],
        ),
    ] = None,
    is_enabled: Annotated[
        bool | None,
        Query(description="按是否启用筛选：true = 已启用；false = 已停用；不传 = 全部", examples=[False]),
    ] = None,
):
    return service.list_provider_specs(
        db, provider_code=provider_code, keyword=keyword, is_enabled=is_enabled, page=page
    )


@admin_router.post(
    "/provider-specs",
    operation_id="admin_provider_specs_create",
    summary="新增服务商规格",
    description=f"配置服务商可办理的规格、服务商侧规格 ID 和成本。同一服务商与规格只能有一条配置。权限点 provider:write。{_LOGIN_NOTE}{_WRITE_NOTE}",
    response_model=AdminProviderSpecOut,
    response_description="新建的服务商规格配置",
    responses=errors_doc(
        *_AUTH, ErrorCode.NOT_FOUND, ErrorCode.SPEC_NOT_FOUND, ErrorCode.CONFLICT, ErrorCode.VALIDATION_ERROR
    ),
)
def create_provider_spec(body: AdminProviderSpecCreateIn, admin: ProviderWrite, db: DB):
    return service.create_provider_spec(db, admin, body)


@admin_router.patch(
    "/provider-specs/{entry_id}",
    operation_id="admin_provider_specs_update",
    summary="修改服务商规格",
    description=f"按服务商列表提供的记录 ID 更新配置。省略的字段保持原值，字段值不能为 null。权限点 provider:write。{_LOGIN_NOTE}{_WRITE_NOTE}",
    response_model=AdminProviderSpecOut,
    response_description="修改后的服务商规格配置",
    responses=errors_doc(
        *_AUTH, ErrorCode.NOT_FOUND, ErrorCode.SPEC_NOT_FOUND, ErrorCode.CONFLICT, ErrorCode.VALIDATION_ERROR
    ),
)
def update_provider_spec(
    entry_id: ProviderSpecIdPath, body: AdminProviderSpecUpdateIn, admin: ProviderWrite, db: DB
):
    return service.update_provider_spec(db, admin, entry_id, body)


@admin_router.delete(
    "/provider-specs/{entry_id}",
    operation_id="admin_provider_specs_delete",
    summary="删除服务商规格",
    description=f"删除服务商规格配置后，引用该服务商和规格的规则无法匹配此配置。权限点 provider:write。{_LOGIN_NOTE}{_WRITE_NOTE}",
    response_model=OkResponse,
    response_description="服务商规格配置已删除",
    responses=errors_doc(*_AUTH, ErrorCode.NOT_FOUND, ErrorCode.VALIDATION_ERROR),
)
def delete_provider_spec(entry_id: ProviderSpecIdPath, admin: ProviderWrite, db: DB):
    return service.delete_provider_spec(db, admin, entry_id)


@admin_router.get(
    "/route-rules",
    operation_id="admin_route_rules_list",
    summary="路由规则列表",
    description=(
        f"分页列出路由规则（某规格、某地区下的候选服务商及优先级），按创建时间从新到旧，"
        f"条件之间是“并且”。权限点 provider:read。{_LOGIN_NOTE}"
    ),
    response_model=AdminRouteRulePage,
    response_description="路由规则分页列表",
    responses=errors_doc(*_AUTH),
)
def list_route_rules(
    _: ProviderRead,
    db: DB,
    page: Page,
    provider_code: Annotated[
        str | None,
        Query(max_length=64, description="按服务商编码筛选；不存在的编码返回空列表", examples=["zheying"]),
    ] = None,
    spec_code: Annotated[
        str | None, Query(max_length=64, description="按规格编码精确筛选", examples=["gd_idcard"])
    ] = None,
):
    return service.list_route_rules(db, provider_code=provider_code, spec_code=spec_code, page=page)


@admin_router.post(
    "/route-rules",
    operation_id="admin_route_rules_create",
    summary="新增路由规则",
    description=f"配置规格在指定地区的候选服务商。地区为空表示不限。同一规格、地区与服务商只能有一条规则。实际路由还需匹配已启用的服务商规格。权限点 provider:write。{_LOGIN_NOTE}{_WRITE_NOTE}",
    response_model=AdminRouteRuleOut,
    response_description="新建的路由规则",
    responses=errors_doc(
        *_AUTH, ErrorCode.NOT_FOUND, ErrorCode.SPEC_NOT_FOUND, ErrorCode.CONFLICT, ErrorCode.VALIDATION_ERROR
    ),
)
def create_route_rule(body: AdminRouteRuleCreateIn, admin: ProviderWrite, db: DB):
    return service.create_route_rule(db, admin, body)


@admin_router.patch(
    "/route-rules/{rule_id}",
    operation_id="admin_route_rules_update",
    summary="修改路由规则",
    description=f"按服务商列表提供的规则 ID 修改配置。省略的字段保持原值，地区可传 null 改为不限。权限点 provider:write。{_LOGIN_NOTE}{_WRITE_NOTE}",
    response_model=AdminRouteRuleOut,
    response_description="修改后的路由规则",
    responses=errors_doc(
        *_AUTH, ErrorCode.NOT_FOUND, ErrorCode.SPEC_NOT_FOUND, ErrorCode.CONFLICT, ErrorCode.VALIDATION_ERROR
    ),
)
def update_route_rule(rule_id: RouteRuleIdPath, body: AdminRouteRuleUpdateIn, admin: ProviderWrite, db: DB):
    return service.update_route_rule(db, admin, rule_id, body)


@admin_router.delete(
    "/route-rules/{rule_id}",
    operation_id="admin_route_rules_delete",
    summary="删除路由规则",
    description=f"删除一个候选服务商规则，后续路由不再根据该规则选取服务商。权限点 provider:write。{_LOGIN_NOTE}{_WRITE_NOTE}",
    response_model=OkResponse,
    response_description="路由规则已删除",
    responses=errors_doc(*_AUTH, ErrorCode.NOT_FOUND, ErrorCode.VALIDATION_ERROR),
)
def delete_route_rule(rule_id: RouteRuleIdPath, admin: ProviderWrite, db: DB):
    return service.delete_route_rule(db, admin, rule_id)


# ---------- 看板与通知 ----------


@admin_router.get(
    "/stats/overview",
    operation_id="admin_stats_overview",
    summary="后台数据看板",
    description=f"查询累计用户数、订单数、支付过的订单数、实付总额和回执各状态数量。实付金额单位为分，包含已退款的原实付额。权限点 stats:read。{_LOGIN_NOTE}",
    response_model=AdminStatsOverviewOut,
    response_description="累计业务指标",
    responses=errors_doc(*_AUTH),
)
def stats_overview(_: StatsRead, db: DB):
    return service.stats_overview(db)


@admin_router.get(
    "/notify-tasks",
    operation_id="admin_notify_tasks_list",
    summary="通知任务列表",
    description=f"按通知任务 ID 从大到小查询，可按状态筛选和游标翻页。返回任务状态、渠道、时间及关联记录 ID。权限点 notify:read。{_LOGIN_NOTE}",
    response_model=AdminNotifyTaskPage,
    response_description="通知任务分页列表",
    responses=errors_doc(*_AUTH, ErrorCode.VALIDATION_ERROR),
)
def list_notify_tasks(
    _: NotifyRead,
    db: DB,
    page: Page,
    status: Annotated[
        NotifyStatus | None, Query(description=f"按状态筛选。{NOTIFY_STATUS_DOC}", examples=["pending"])
    ] = None,
):
    return service.list_notify_tasks(db, status=status, page=page)


# ---------- 管理员账号 ----------


@admin_router.get(
    "/admin-users",
    operation_id="admin_accounts_list",
    summary="管理员账号列表",
    description=f"按账号 ID 从大到小分页，返回管理员角色和启用状态。权限点 admin:read（仅 owner）。{_LOGIN_NOTE}",
    response_model=AdminAccountPage,
    response_description="管理员账号分页列表",
    responses=errors_doc(*_AUTH, ErrorCode.VALIDATION_ERROR),
)
def list_admin_accounts(_: AdminAccountRead, db: DB, page: Page):
    return service.list_admin_accounts(db, page)


@admin_router.post(
    "/admin-users",
    operation_id="admin_accounts_create",
    summary="新建管理员账号",
    description=f"按用户名、初始密码和角色创建一个启用的后台账号。用户名区分大小写且唯一。权限点 admin:write（仅 owner）。{_LOGIN_NOTE}{_WRITE_NOTE}",
    response_model=AdminAccountOut,
    response_description="新建的后台账号资料",
    responses=errors_doc(*_AUTH, ErrorCode.CONFLICT, ErrorCode.VALIDATION_ERROR),
)
def create_admin_account(body: AdminAccountCreateIn, admin: AdminAccountWrite, db: DB):
    return service.create_admin_account(db, admin, body)


@admin_router.post(
    "/admin-users/{admin_id}/disable",
    operation_id="admin_accounts_disable",
    summary="停用管理员账号",
    description=f"停用账号并吊销其所有会话，账号再次停用仍返回成功。不能停用自己或最后一个启用的 owner。权限点 admin:write（仅 owner）。{_LOGIN_NOTE}{_WRITE_NOTE}",
    response_model=AdminAccountOut,
    response_description="停用后的后台账号资料",
    responses=errors_doc(*_AUTH, ErrorCode.NOT_FOUND, ErrorCode.CONFLICT, ErrorCode.VALIDATION_ERROR),
)
def disable_admin_account(admin_id: AdminIdPath, admin: AdminAccountWrite, db: DB):
    return service.disable_admin_account(db, admin, admin_id)


@admin_router.patch(
    "/admin-users/{admin_id}/role",
    operation_id="admin_accounts_update_role",
    summary="修改管理员角色",
    description=f"替换账号的角色，后续请求使用该角色的权限。不能降低自己或最后一个启用的 owner 的角色。权限点 admin:write（仅 owner）。{_LOGIN_NOTE}{_WRITE_NOTE}",
    response_model=AdminAccountOut,
    response_description="角色变更后的后台账号资料",
    responses=errors_doc(*_AUTH, ErrorCode.NOT_FOUND, ErrorCode.CONFLICT, ErrorCode.VALIDATION_ERROR),
)
def update_admin_role(admin_id: AdminIdPath, body: AdminAccountRoleIn, admin: AdminAccountWrite, db: DB):
    return service.update_admin_role(db, admin, admin_id, body)


@admin_router.post(
    "/admin-users/{admin_id}/reset-password",
    operation_id="admin_accounts_reset_password",
    summary="重置管理员密码",
    description=f"为启用的账号生成一次性临时密码并吊销其所有会话。临时密码仅随本次响应返回，使用时须先在登录请求中设置正式密码。权限点 admin:write（仅 owner）。{_LOGIN_NOTE}{_WRITE_NOTE}",
    response_model=AdminPasswordResetOut,
    response_description="临时密码，成功使用一次即失效",
    responses=errors_doc(*_AUTH, ErrorCode.NOT_FOUND, ErrorCode.ACCOUNT_DISABLED, ErrorCode.VALIDATION_ERROR),
)
def reset_admin_password(admin_id: AdminIdPath, response: Response, admin: AdminAccountWrite, db: DB):
    out = service.reset_admin_password(db, admin, admin_id)
    response.headers["Cache-Control"] = "no-store"
    return out


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
