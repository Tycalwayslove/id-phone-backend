"""运营后台的请求和返回模型。所有模型以 Admin 开头，避免和 C 端模型重名。"""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.core.schemas import Schema, page_model
from app.modules.orders.schemas import OrderItemOut
from app.modules.specs.schemas import SpecFormField

AdminRole = Literal["owner", "operator", "finance"]
AdminAccountStatus = Literal["active", "disabled"]
UserStatus = Literal["active", "disabled", "cancelled"]
OrderStatus = Literal["pending", "paid", "closed", "part_refunded", "refunded"]
ApplicationStatus = Literal["pending", "processing", "rejected", "completed", "failed", "cancelled"]
AttemptStatus = Literal[
    "created", "submitted", "unknown", "processing", "completed", "rejected", "failed", "abandoned"
]
PlanStatus = Literal["draft", "on_sale", "off_sale"]
SpecStatus = Literal["active", "inactive"]
SpecCategory = Literal["receipt", "normal", "exam"]
ProviderStatus = Literal["enabled", "disabled", "circuit_open"]
NotifyStatus = Literal["pending", "sent", "failed", "skipped", "cancelled"]
NotifyEvent = Literal["receipt_rejected", "receipt_completed", "entitlement_expiring", "receipt_expiring"]
NotifyChannel = Literal["mini_subscribe", "mp_template", "wecom", "sms", "voice", "manual_call"]

_PLAN_STATUS_DOC = "draft = 草稿，用户看不到；on_sale = 在售（还要在销售时间窗口内才能买）；off_sale = 已下架，不能再买，已买的权益不受影响"
_ROLE_DOC = "角色：owner = 所有者，拥有全部权限；operator = 运营，管用户/回执/规格，不能退款和改套餐；finance = 财务，可退款、看订单和用户"
NOTIFY_STATUS_DOC = "pending = 待发送；sent = 已发送；failed = 发送失败；skipped = 跳过；cancelled = 已取消"
AdminPassword = Annotated[str, StringConstraints(min_length=12, max_length=128)]
RoutingCode = Annotated[str, StringConstraints(min_length=1, max_length=64)]
RoutingRegionCode = Annotated[str, StringConstraints(min_length=1, max_length=32)]

# ---------- 登录 ----------


class AdminLoginIn(Schema):
    """后台登录请求。"""

    username: str = Field(
        min_length=1, max_length=64, description="后台账号用户名，区分大小写", examples=["ops_zhang"]
    )
    password: str = Field(
        min_length=1, max_length=128, repr=False, description="登录密码", examples=["a-long-password-123"]
    )
    new_password: AdminPassword | None = Field(
        default=None,
        repr=False,
        description="使用重置得到的临时密码时必填，设置 12～128 字符且不同于临时密码的正式密码",
        examples=["another-long-password-456"],
    )


class AdminBriefOut(Schema):
    """后台账号的简要信息。"""

    id: int = Field(description="后台账号 ID", examples=[3])
    username: str = Field(description="用户名", examples=["ops_zhang"])
    role: AdminRole = Field(description=_ROLE_DOC, examples=["operator"])


class AdminLoginOut(Schema):
    """登录成功的返回。会话令牌通过 httpOnly Cookie（admin_session）下发，前端拿不到也不需要拿。"""

    csrf_token: str = Field(
        description="防跨站请求伪造令牌。之后所有 POST/PATCH/DELETE 请求都必须在请求头 X-CSRF-Token 里带上它；GET 请求不需要",
        examples=["3f2a9c7e1b5d4a6f8e0c2b4d6a8f0e1c"],
    )
    admin: AdminBriefOut = Field(description="当前登录的后台账号")


class AdminMeOut(Schema):
    """当前后台账号及其权限。"""

    id: int = Field(description="后台账号 ID", examples=[3])
    username: str = Field(description="用户名", examples=["ops_zhang"])
    role: AdminRole = Field(description=_ROLE_DOC, examples=["operator"])
    permissions: list[str] = Field(
        description="该账号拥有的全部权限点，格式 资源:动作（如 refund:create）。前端按它显示或隐藏菜单和按钮；owner 返回全部权限点",
        examples=[["user:read", "order:read", "application:read"]],
    )


# ---------- 管理员账号 ----------


class AdminAccountOut(AdminBriefOut):
    """用于账号管理的管理员资料。"""

    status: AdminAccountStatus = Field(description="active = 正常；disabled = 已停用", examples=["active"])
    created_at: datetime = Field(description="创建时间（UTC，带时区）", examples=["2026-11-19T09:00:00Z"])
    updated_at: datetime = Field(description="更新时间（UTC，带时区）", examples=["2026-11-19T09:00:00Z"])


AdminAccountPage = page_model(AdminAccountOut, "AdminAccountPage")


class AdminAccountCreateIn(Schema):
    """新建启用的后台账号。"""

    username: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^\S+$",
        description="后台用户名，1～64 字符，区分大小写，不含空白字符",
        examples=["ops_zhang"],
    )
    password: AdminPassword = Field(
        repr=False, description="初始登录密码，12～128 字符", examples=["a-long-password-123"]
    )
    role: AdminRole = Field(description=_ROLE_DOC, examples=["operator"])


class AdminAccountRoleIn(Schema):
    """修改后台账号角色。"""

    role: AdminRole = Field(description=_ROLE_DOC, examples=["finance"])


class AdminPasswordResetOut(Schema):
    """密码重置后仅本次响应提供的登录凭据。"""

    temporary_password: str = Field(
        repr=False,
        description="临时密码，只在此响应提供。登录时须同时设置正式密码，成功后临时密码失效",
        examples=["example-temporary-password"],
    )


# ---------- 看板与通知 ----------


class AdminStatsOverviewOut(Schema):
    """后台数据看板的全量累计指标。"""

    user_count: int = Field(description="用户总数，含已停用和已注销的用户", examples=[120])
    order_count: int = Field(description="全部订单数，含未支付和关闭的订单", examples=[95])
    paid_order_count: int = Field(description="成功支付过的订单数，含部分退款和全额退款订单", examples=[80])
    paid_total_fen: int = Field(description="订单累计实付金额，单位分，未扣减退款", examples=[319200])
    receipt_count: int = Field(description="回执申请总数", examples=[25])
    receipt_counts_by_status: dict[ApplicationStatus, int] = Field(
        description=(
            "各状态的回执申请数量，缺少记录的状态为 0。pending = 已创建未提交；processing = 办理中；"
            "rejected = 已驳回；completed = 已完成；failed = 办理失败；cancelled = 已取消"
        ),
        examples=[
            {"pending": 0, "processing": 2, "rejected": 1, "completed": 20, "failed": 1, "cancelled": 1}
        ],
    )


class AdminNotifyTaskOut(Schema):
    """通知任务的状态信息。"""

    id: int = Field(description="通知任务 ID", examples=[76])
    user_id: int = Field(description="接收通知的用户 ID", examples=[1024])
    application_id: int | None = Field(description="关联回执申请 ID，关联权益时为空", examples=[81])
    entitlement_id: int | None = Field(description="关联权益 ID，关联回执申请时为空", examples=[None])
    event: NotifyEvent = Field(
        description=(
            "receipt_rejected = 回执驳回；receipt_completed = 回执办理完成；"
            "entitlement_expiring = 权益即将到期；receipt_expiring = 回执即将到期"
        ),
        examples=["receipt_completed"],
    )
    step: int = Field(description="通知档位，用于区分升级步骤或到期提醒档次", examples=[1])
    channel: NotifyChannel = Field(
        description=(
            "mini_subscribe = 小程序订阅消息；mp_template = 公众号模板消息；wecom = 企业微信；"
            "sms = 短信；voice = 语音；manual_call = 人工电话"
        ),
        examples=["mini_subscribe"],
    )
    status: NotifyStatus = Field(description=NOTIFY_STATUS_DOC, examples=["pending"])
    scheduled_at: datetime = Field(
        description="计划发送时间（UTC，带时区）", examples=["2026-11-19T09:00:00Z"]
    )
    sent_at: datetime | None = Field(description="实际发送时间（UTC，带时区），未发送时为空", examples=[None])
    created_at: datetime = Field(description="创建时间（UTC，带时区）", examples=["2026-11-19T09:00:00Z"])


AdminNotifyTaskPage = page_model(AdminNotifyTaskOut, "AdminNotifyTaskPage")


# ---------- 用户 ----------


class AdminUserSearchIn(Schema):
    """后台用户查询条件和分页参数。"""

    phone: str | None = Field(
        default=None,
        min_length=5,
        max_length=20,
        description="按完整手机号精确查找。传明文手机号，服务端用哈希匹配；不传则不按手机号筛选",
        examples=["13800001234"],
    )
    user_id: int | None = Field(default=None, ge=1, description="按用户 ID 精确查找", examples=[1024])
    status: UserStatus | None = Field(
        default=None,
        description="按账号状态筛选：active = 正常；disabled = 已停用；cancelled = 已注销",
        examples=["active"],
    )
    cursor: str | None = Field(
        default=None,
        description="翻页游标。第一页不传，之后传上一页返回的 next_cursor",
        examples=["eyJpIjoxMDI0fQ"],
    )
    limit: int = Field(default=20, ge=1, le=100, description="每页条数，1～100，默认 20", examples=[20])


class AdminUserOut(Schema):
    """用户摘要（后台列表用）。手机号只返回打码后的。"""

    id: int = Field(description="用户 ID", examples=[1024])
    nickname: str | None = Field(description="昵称；用户还没设置时为空", examples=["小明"])
    phone_masked: str | None = Field(
        description="打码后的手机号；没绑定或已注销时为空", examples=["138****1234"]
    )
    status: UserStatus = Field(
        description="账号状态：active = 正常；disabled = 已停用，不能登录；cancelled = 用户已注销",
        examples=["active"],
    )
    created_at: datetime = Field(description="注册时间（UTC，带时区）", examples=["2026-11-19T08:30:12Z"])
    last_active_at: datetime | None = Field(
        description="最近活跃时间（UTC，带时区）；从未活跃时为空", examples=["2026-11-19T09:00:00Z"]
    )
    identities: list[str] = Field(
        description="该用户绑定的登录身份类型：wx_mini = 微信小程序；wx_mp = 公众号；alipay_mini = 支付宝小程序；douyin_mini = 抖音小程序；h5 = 网页",
        examples=[["wx_mini"]],
    )
    orders_count: int = Field(
        description="已支付过的订单数（含后来退款的订单；待支付和已关闭的不算）", examples=[2]
    )
    paid_fen_total: int = Field(
        description="累计实付金额，单位：分；是各订单已支付金额之和，不扣除退款", examples=[3990]
    )


class AdminUserDetail(AdminUserOut):
    """用户详情：在摘要基础上增加头像和回执申请数。"""

    avatar_url: str | None = Field(
        description="头像链接；没设置时为空", examples=["https://example.com/a.png"]
    )
    applications_count: int = Field(description="该用户提交过的回执申请总数（含已取消）", examples=[1])


AdminUserPage = page_model(AdminUserOut, "AdminUserPage")

# ---------- 订单与退款 ----------


class AdminPaymentOut(Schema):
    """订单的一条支付流水。"""

    channel: str = Field(
        description="支付渠道：wxpay = 微信支付；alipay = 支付宝；douyin_pay = 抖音支付", examples=["wxpay"]
    )
    out_trade_no: str = Field(description="商户支付单号", examples=["P20261119083012A1B2C3"])
    transaction_id: str | None = Field(
        description="渠道交易号；未支付成功时为空", examples=["4200001234202611190001"]
    )
    amount_fen: int = Field(description="支付金额，单位：分", examples=[3990])
    status: Literal["pending", "success", "failed", "closed"] = Field(
        description="流水状态：pending = 待支付；success = 支付成功；failed = 支付失败；closed = 已关闭",
        examples=["success"],
    )
    paid_at: datetime | None = Field(
        description="支付成功时间（UTC，带时区）；未成功时为空", examples=["2026-11-19T08:31:00Z"]
    )


class AdminRefundOut(Schema):
    """一条退款记录。"""

    out_refund_no: str = Field(description="商户退款单号", examples=["F20261119090000A1B2C3"])
    amount_fen: int = Field(description="退款金额，单位：分", examples=[3990])
    reason: str = Field(description="退款原因（操作人填写）", examples=["用户重复购买"])
    status: Literal["pending", "success", "failed"] = Field(
        description="退款状态：pending = 处理中，等待渠道结果；success = 退款成功；failed = 退款失败，订单金额不变",
        examples=["success"],
    )
    operator: str = Field(description="操作人：后台账号用户名，系统自动退款时为 system", examples=["fin_li"])
    created_at: datetime = Field(
        description="发起退款的时间（UTC，带时区）", examples=["2026-11-19T09:00:00Z"]
    )
    finished_at: datetime | None = Field(
        description="退款出结果的时间；处理中为空", examples=["2026-11-19T09:00:01Z"]
    )


class AdminRefundResultOut(AdminRefundOut):
    """发起退款的结果：退款记录加上订单退款后的状态。"""

    order_no: str = Field(description="订单号", examples=["O20261119083012A1B2C3"])
    order_status: OrderStatus = Field(
        description="退款后的订单状态：part_refunded = 部分退款；refunded = 已全额退款；退款处理中或失败时保持原状态",
        examples=["refunded"],
    )
    order_refunded_fen: int = Field(description="退款后订单累计已退金额，单位：分", examples=[3990])


class AdminOrderOut(Schema):
    """订单摘要（后台列表用）。"""

    order_no: str = Field(description="订单号", examples=["O20261119083012A1B2C3"])
    user_id: int = Field(description="下单用户 ID", examples=[1024])
    status: OrderStatus = Field(
        description="订单状态：pending = 待支付；paid = 已支付；closed = 已关闭（超时或取消）；part_refunded = 部分退款；refunded = 已全额退款",
        examples=["paid"],
    )
    total_fen: int = Field(description="订单应付金额，单位：分", examples=[3990])
    paid_fen: int = Field(description="已支付金额，单位：分；未支付为 0", examples=[3990])
    refunded_fen: int = Field(description="已退款金额，单位：分", examples=[0])
    created_at: datetime = Field(description="下单时间（UTC，带时区）", examples=["2026-11-19T08:30:12Z"])
    paid_at: datetime | None = Field(
        description="支付成功时间；未支付时为空", examples=["2026-11-19T08:31:00Z"]
    )
    items: list[OrderItemOut] = Field(description="订单商品项")


class AdminOrderDetail(AdminOrderOut):
    """订单详情：在摘要基础上增加支付流水和退款记录。"""

    payments: list[AdminPaymentOut] = Field(description="支付流水，按创建先后排列")
    refunds: list[AdminRefundOut] = Field(description="退款记录，按发起先后排列；没有退款为空列表")


AdminOrderPage = page_model(AdminOrderOut, "AdminOrderPage")


class AdminRefundIn(Schema):
    """发起退款的请求。"""

    request_id: UUID = Field(
        description="退款请求 UUID 字符串。前端每次打开退款弹窗时生成，重试同一笔退款时复用",
        examples=["99c238a2-4de7-4d98-a2df-b79f7538cb7e"],
    )
    amount_fen: int = Field(
        gt=0,
        le=100_000_000,
        description="退款金额，单位：分，必须大于 0 且不超过订单可退余额（已付 - 已退 - 处理中退款）",
        examples=[3990],
    )
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = Field(
        description="退款原因，1～200 字，会记入退款记录。不要填手机号、身份证号",
        examples=["用户重复购买"],
    )


# ---------- 回执申请 ----------


class AdminAttemptOut(Schema):
    """一次提交给服务商的记录。"""

    seq: int = Field(description="第几次提交，从 1 开始", examples=[1])
    provider_code: str = Field(description="服务商编码", examples=["zheying"])
    status: AttemptStatus = Field(
        description="提交状态：created = 已创建未发出；submitted = 已提交等待结果；unknown = 超时不确定，系统自动核对；processing = 对方办理中；completed = 已出回执；rejected = 被驳回；failed = 失败；abandoned = 已放弃",
        examples=["rejected"],
    )
    is_current: bool = Field(description="是否当前有效的提交；同一申请只有一条为 true", examples=[True])
    reject_reason: str | None = Field(description="驳回原因；没被驳回为空", examples=["照片背景不均匀"])
    cost_fen: int | None = Field(
        description="服务商收取的成本，单位：分；服务商只在成功时收费，未出结果为空", examples=[300]
    )
    submitted_at: datetime | None = Field(
        description="提交成功时间；还没提交成功为空", examples=["2026-11-19T08:30:00Z"]
    )
    finished_at: datetime | None = Field(
        description="出结果时间；还没出结果为空", examples=["2026-11-19T09:10:00Z"]
    )


class AdminApplicationOut(Schema):
    """回执申请摘要（后台列表用）。"""

    app_no: str = Field(description="申请单号", examples=["R20261119083012A1B2C3"])
    user_id: int = Field(description="申请人用户 ID", examples=[1024])
    status: ApplicationStatus = Field(
        description="申请状态：pending = 已创建未提交；processing = 办理中；rejected = 被驳回，可重提或取消；completed = 已出回执；failed = 办理失败；cancelled = 已取消",
        examples=["processing"],
    )
    manual_review_required: bool = Field(
        description="是否需人工核对。当前提交在真实服务商两小时未取得结果而尚未处理时为 true",
        examples=[True, False],
    )
    spec_code: str = Field(description="规格编码", examples=["gd_idcard"])
    spec_name: str = Field(description="规格名称", examples=["广东省身份证"])
    photo_id: int = Field(description="当前使用的照片 ID", examples=[12])
    entitlement_id: int = Field(description="占用回执次数的权益 ID", examples=[88])
    resubmit_count: int = Field(description="已重新提交的次数，首次提交不算", examples=[0])
    reject_reason: str | None = Field(
        description="当前驳回原因；只在 rejected 时有值", examples=["照片背景不均匀"]
    )
    created_at: datetime = Field(description="创建时间（UTC，带时区）", examples=["2026-11-19T08:30:00Z"])
    updated_at: datetime = Field(description="最近更新时间（UTC，带时区）", examples=["2026-11-19T09:10:00Z"])
    completed_at: datetime | None = Field(
        description="出回执时间；未完成为空", examples=["2026-11-19T09:10:00Z"]
    )


class AdminApplicationDetail(AdminApplicationOut):
    """回执申请详情：增加全部提交记录和打码后的办理表单。"""

    region_code: str | None = Field(description="办理地区行政区划码；不限地区为空", examples=["440300"])
    image_code: str | None = Field(description="回执图像号；只在 completed 时有值", examples=["IMG1A2B3C4D"])
    rejected_at: datetime | None = Field(
        description="被驳回时间；只在 rejected 时有值", examples=["2026-11-19T09:10:00Z"]
    )
    official_expire_at: datetime | None = Field(
        description="官方回执有效截止时间；未知或未出回执为空", examples=["2027-02-17T00:00:00Z"]
    )
    form_masked: dict[str, str] = Field(
        description="打码后的办理表单：姓名只显示姓，身份证号只显示前 3 后 4，手机号中间打码。后台看不到明文",
        examples=[{"name": "张*", "idcard": "110***********0019"}],
    )
    attempts: list[AdminAttemptOut] = Field(description="全部提交记录，按次序从早到晚")


AdminApplicationPage = page_model(AdminApplicationOut, "AdminApplicationPage")


class AdminManualReviewIn(Schema):
    """标记回执申请已人工核对的请求。"""

    result: Literal["completed", "rejected", "failed"] = Field(
        description="核对结论。completed 表示已出回执，rejected 表示被驳回，failed 表示办理失败",
        examples=["completed"],
    )
    remark: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = Field(
        description="核对备注，1～200 字，仅写入后台审计。请勿填写手机号、身份证号、令牌或密钥",
        examples=["已与服务商确认办理结果"],
    )


# ---------- 套餐 ----------

PlanCode = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{2,64}$")]


class AdminPlanOut(Schema):
    """套餐（含草稿和已下架）。"""

    code: str = Field(description="套餐编码，唯一，创建后不可改", examples=["photo_year_39_9"])
    name: str = Field(description="套餐名称", examples=["单张照片年度保管"])
    price_fen: int = Field(description="价格，单位：分（3990 = 39.9 元）", examples=[3990])
    status: PlanStatus = Field(description=f"套餐状态：{_PLAN_STATUS_DOC}", examples=["on_sale"])
    sort: int = Field(description="排序值，越小越靠前", examples=[20])
    sale_starts_at: datetime | None = Field(
        description="开售时间；为空表示不限", examples=["2026-11-01T00:00:00Z"]
    )
    sale_ends_at: datetime | None = Field(description="停售时间；为空表示不限", examples=[None])
    display: dict[str, Any] = Field(
        description="展示配置（卖点、角标等），原样返回给小程序", examples=[{"badge": "推荐"}]
    )
    benefits: dict[str, int] = Field(
        description="权益配置：权益类型 → 数值。类型：storage_days 保管天数；photo_scope 1=单张照片 0=全部照片；receipt_quota 回执次数；resubmit_limit 驳回后免费重提次数；spec_change 1=可换规格；one_person 1=一卡一人；attach_to_parent 1=加购项",
        examples=[{"storage_days": 365, "photo_scope": 1, "receipt_quota": 1}],
    )
    created_at: datetime = Field(description="创建时间（UTC，带时区）", examples=["2026-11-01T00:00:00Z"])
    updated_at: datetime = Field(description="最近修改时间（UTC，带时区）", examples=["2026-11-19T00:00:00Z"])


class AdminPlanCreateIn(Schema):
    """创建套餐的请求。"""

    code: PlanCode = Field(
        description="套餐编码，2～64 位小写字母、数字、下划线；全局唯一，创建后不可改",
        examples=["photo_year_39_9"],
    )
    name: str = Field(min_length=1, max_length=64, description="套餐名称", examples=["单张照片年度保管"])
    price_fen: int = Field(ge=0, le=100_000_000, description="价格，单位：分", examples=[3990])
    status: PlanStatus = Field(
        default="draft", description=f"套餐状态，默认 draft：{_PLAN_STATUS_DOC}", examples=["draft"]
    )
    sort: int = Field(default=0, ge=-10000, le=10000, description="排序值，越小越靠前", examples=[20])
    sale_starts_at: datetime | None = Field(
        default=None, description="开售时间（带时区）；不传表示不限", examples=[None]
    )
    sale_ends_at: datetime | None = Field(
        default=None, description="停售时间（带时区），必须晚于开售时间；不传表示不限", examples=[None]
    )
    display: dict[str, Any] = Field(
        default_factory=dict, description="展示配置，原样返回给小程序", examples=[{"badge": "推荐"}]
    )
    benefits: dict[str, int] = Field(
        description="权益配置：权益类型 → 非负整数。类型必须是 storage_days、photo_scope、receipt_quota、resubmit_limit、spec_change、one_person、attach_to_parent 之一",
        examples=[{"storage_days": 365, "photo_scope": 1, "receipt_quota": 1}],
    )


class AdminPlanUpdateIn(Schema):
    """修改套餐的请求。只改传了的字段；已售出的权益用购买时的快照，修改套餐不影响已买的。"""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="新名称；不传表示不改",
        examples=["单张照片年度保管"],
    )
    price_fen: int | None = Field(
        default=None, ge=0, le=100_000_000, description="新价格，单位：分；不传表示不改", examples=[3490]
    )
    status: PlanStatus | None = Field(
        default=None, description=f"新状态；不传表示不改。{_PLAN_STATUS_DOC}", examples=["off_sale"]
    )
    sort: int | None = Field(
        default=None, ge=-10000, le=10000, description="新排序值；不传表示不改", examples=[10]
    )
    sale_starts_at: datetime | None = Field(
        default=None, description="新开售时间；不传表示不改，传 null 表示清除限制", examples=[None]
    )
    sale_ends_at: datetime | None = Field(
        default=None, description="新停售时间；不传表示不改，传 null 表示清除限制", examples=[None]
    )
    display: dict[str, Any] | None = Field(
        default=None, description="新展示配置，整体替换；不传表示不改", examples=[{"badge": "限时"}]
    )
    benefits: dict[str, int] | None = Field(
        default=None,
        description="新权益配置，传了就整体替换（没写的权益类型会被删除）；不传表示不改。类型和取值同创建套餐",
        examples=[{"storage_days": 365, "photo_scope": 1, "receipt_quota": 1}],
    )


# ---------- 规格 ----------

HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]


class AdminSpecOut(Schema):
    """规格（含已下架）。"""

    code: str = Field(description="规格编码，唯一，创建后不可改", examples=["gd_idcard"])
    name: str = Field(description="规格名称", examples=["广东省身份证"])
    parent_code: str | None = Field(description="父规格编码；顶级规格为空", examples=[None])
    category: SpecCategory = Field(
        description="分类：receipt = 回执类；normal = 普通证件照；exam = 考试报名照", examples=["receipt"]
    )
    cert_type: str = Field(description="证件类型标识", examples=["idcard"])
    region_code: str | None = Field(description="适用地区行政区划码；不限地区为空", examples=["440000"])
    width_px: int = Field(description="成品宽度，像素", examples=[358])
    height_px: int = Field(description="成品高度，像素", examples=[441])
    width_mm: int | None = Field(description="成品宽度，毫米；官方未规定为空", examples=[26])
    height_mm: int | None = Field(description="成品高度，毫米；官方未规定为空", examples=[32])
    dpi: int = Field(description="分辨率，dpi", examples=[300])
    bg_colors: list[str] = Field(
        description="可选底色（十六进制），第一项为默认底色", examples=[["#FFFFFF", "#438EDB"]]
    )
    file_size_min_kb: int | None = Field(description="文件大小下限，KB；无要求为空", examples=[None])
    file_size_max_kb: int | None = Field(description="文件大小上限，KB；无要求为空", examples=[100])
    beauty_max: int = Field(description="允许的最高美颜档位 0～5；0 = 不允许美颜", examples=[3])
    form_schema: list[SpecFormField] = Field(description="办理回执时用户要填写的字段；不办回执的规格为空列表")
    official_valid_days: int | None = Field(description="官方回执有效天数；无明确期限为空", examples=[90])
    status: SpecStatus = Field(
        description="状态：active = 上架；inactive = 下架（用户端看不到，已有申请不受影响）",
        examples=["active"],
    )
    sort: int = Field(description="排序值，越小越靠前", examples=[0])
    created_at: datetime = Field(description="创建时间（UTC，带时区）", examples=["2026-11-01T00:00:00Z"])
    updated_at: datetime = Field(description="最近修改时间（UTC，带时区）", examples=["2026-11-19T00:00:00Z"])


AdminSpecPage = page_model(AdminSpecOut, "AdminSpecPage")


class AdminSpecCreateIn(Schema):
    """创建规格的请求。"""

    code: PlanCode = Field(
        description="规格编码，2～64 位小写字母、数字、下划线；全局唯一，创建后不可改", examples=["gd_idcard"]
    )
    name: str = Field(
        min_length=1, max_length=64, description="规格名称，展示给用户", examples=["广东省身份证"]
    )
    parent_code: str | None = Field(
        default=None, max_length=64, description="父规格编码，必须已存在；顶级规格不传", examples=[None]
    )
    category: SpecCategory = Field(
        description="分类：receipt = 回执类；normal = 普通证件照；exam = 考试报名照", examples=["receipt"]
    )
    cert_type: str = Field(
        min_length=1, max_length=32, description="证件类型标识，如 idcard", examples=["idcard"]
    )
    region_code: str | None = Field(
        default=None, max_length=12, description="适用地区行政区划码；不限地区不传", examples=["440000"]
    )
    width_px: int = Field(gt=0, le=10000, description="成品宽度，像素", examples=[358])
    height_px: int = Field(gt=0, le=10000, description="成品高度，像素", examples=[441])
    width_mm: int | None = Field(
        default=None, gt=0, le=1000, description="成品宽度，毫米；官方未规定不传", examples=[26]
    )
    height_mm: int | None = Field(
        default=None, gt=0, le=1000, description="成品高度，毫米；官方未规定不传", examples=[32]
    )
    dpi: int = Field(default=300, gt=0, le=1200, description="分辨率，默认 300", examples=[300])
    bg_colors: list[HexColor] = Field(
        min_length=1,
        max_length=10,
        description="可选底色，十六进制如 #FFFFFF，至少一个，第一项为默认",
        examples=[["#FFFFFF", "#438EDB"]],
    )
    file_size_min_kb: int | None = Field(
        default=None, ge=0, description="文件大小下限，KB；无要求不传", examples=[None]
    )
    file_size_max_kb: int | None = Field(
        default=None, gt=0, description="文件大小上限，KB，不能小于下限；无要求不传", examples=[100]
    )
    beauty_max: int = Field(
        default=0, ge=0, le=5, description="允许的最高美颜档位 0～5，默认 0 = 不允许美颜", examples=[3]
    )
    form_schema: list[SpecFormField] = Field(
        default_factory=list, max_length=20, description="办理回执时用户要填写的字段；不办回执不传"
    )
    official_valid_days: int | None = Field(
        default=None, gt=0, description="官方回执有效天数；无明确期限不传", examples=[90]
    )
    status: SpecStatus = Field(
        default="active", description="状态：active = 上架（默认）；inactive = 下架", examples=["active"]
    )
    sort: int = Field(default=0, ge=-10000, le=10000, description="排序值，越小越靠前", examples=[0])


class AdminSpecUpdateIn(Schema):
    """修改规格的请求。只改传了的字段（可空字段传 null 表示清空）；编码和父规格不可改。"""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="新名称；不传表示不改",
        examples=["广东省身份证"],
    )
    category: SpecCategory | None = Field(
        default=None, description="新分类；不传表示不改", examples=["receipt"]
    )
    cert_type: str | None = Field(
        default=None, min_length=1, max_length=32, description="新证件类型；不传表示不改", examples=["idcard"]
    )
    region_code: str | None = Field(
        default=None,
        max_length=12,
        description="新地区码；不传表示不改，传 null 表示不限地区",
        examples=["440000"],
    )
    width_px: int | None = Field(
        default=None, gt=0, le=10000, description="新宽度，像素；不传表示不改", examples=[358]
    )
    height_px: int | None = Field(
        default=None, gt=0, le=10000, description="新高度，像素；不传表示不改", examples=[441]
    )
    width_mm: int | None = Field(
        default=None, gt=0, le=1000, description="新宽度，毫米；不传表示不改，传 null 表示清空", examples=[26]
    )
    height_mm: int | None = Field(
        default=None, gt=0, le=1000, description="新高度，毫米；不传表示不改，传 null 表示清空", examples=[32]
    )
    dpi: int | None = Field(default=None, gt=0, le=1200, description="新分辨率；不传表示不改", examples=[300])
    bg_colors: list[HexColor] | None = Field(
        default=None,
        min_length=1,
        max_length=10,
        description="新底色列表，整体替换；不传表示不改",
        examples=[["#FFFFFF"]],
    )
    file_size_min_kb: int | None = Field(
        default=None, ge=0, description="新文件大小下限 KB；不传表示不改，传 null 表示清空", examples=[None]
    )
    file_size_max_kb: int | None = Field(
        default=None, gt=0, description="新文件大小上限 KB；不传表示不改，传 null 表示清空", examples=[100]
    )
    beauty_max: int | None = Field(
        default=None, ge=0, le=5, description="新美颜上限 0～5；不传表示不改", examples=[3]
    )
    form_schema: list[SpecFormField] | None = Field(
        default=None, max_length=20, description="新办理表单字段，整体替换；不传表示不改"
    )
    official_valid_days: int | None = Field(
        default=None, gt=0, description="新官方有效天数；不传表示不改，传 null 表示清空", examples=[90]
    )
    status: SpecStatus | None = Field(
        default=None,
        description="新状态：active = 上架；inactive = 下架；不传表示不改",
        examples=["inactive"],
    )
    sort: int | None = Field(
        default=None, ge=-10000, le=10000, description="新排序值；不传表示不改", examples=[0]
    )


# ---------- 服务商 ----------


class AdminProviderSpecOut(Schema):
    """服务商能办理的一个规格（覆盖矩阵的一行）。"""

    id: int = Field(description="服务商规格记录 ID", examples=[71])
    provider_code: str = Field(description="服务商编码", examples=["zheying"])
    spec_code: str = Field(description="规格编码", examples=["gd_idcard"])
    spec_name: str = Field(description="规格名称", examples=["广东省身份证"])
    provider_item_id: str = Field(description="服务商那边的规格 ID", examples=["713"])
    param_mapping: dict[str, Any] = Field(
        description="办理字段到服务商字段名的映射，空对象表示未配置", examples=[{"name": "text_name"}]
    )
    cost_fen: int = Field(description="办理一次的成本，单位：分", examples=[300])
    is_enabled: bool = Field(description="该服务商是否启用此规格", examples=[True])
    last_synced_at: datetime | None = Field(
        description="最近一次同步覆盖范围的时间；从未同步为空", examples=[None]
    )


class AdminRouteRuleOut(Schema):
    """路由规则的一行：某规格（可限地区）下的一个候选服务商。"""

    id: int = Field(description="路由规则 ID", examples=[86])
    provider_code: str = Field(description="服务商编码", examples=["zheying"])
    spec_code: str = Field(description="规格编码", examples=["gd_idcard"])
    region_code: str | None = Field(description="适用地区行政区划码；为空 = 不限地区", examples=[None])
    priority: int = Field(description="优先级，数字越小越优先", examples=[10])
    is_enabled: bool = Field(description="规则是否启用", examples=[True])


class AdminProviderOut(Schema):
    """回执服务商。不返回密钥等配置。"""

    code: str = Field(description="服务商编码，唯一", examples=["zheying"])
    name: str = Field(description="服务商名称", examples=["鹧应"])
    adapter: str = Field(description="代码里使用的适配器名", examples=["zheying"])
    upstream_group: str | None = Field(
        description="上游分组；相同取值的服务商是同一个上游，不会互为备份。无分组为空", examples=["zheying"]
    )
    status: ProviderStatus = Field(
        description="状态：enabled = 启用；disabled = 手动停用，不再接新单；circuit_open = 已熔断（连续故障自动暂停），排查后可改回 enabled",
        examples=["enabled"],
    )
    updated_at: datetime = Field(description="最近修改时间（UTC，带时区）", examples=["2026-11-19T00:00:00Z"])
    provider_specs: list[AdminProviderSpecOut] = Field(description="该服务商能办理的规格")
    route_rules: list[AdminRouteRuleOut] = Field(description="该服务商参与的路由规则")


class AdminProviderUpdateIn(Schema):
    """修改服务商状态的请求。"""

    status: ProviderStatus = Field(
        description="新状态：enabled = 启用；disabled = 停用，不再接新单；circuit_open = 手动熔断，同 disabled 效果，路由会跳过它",
        examples=["disabled"],
    )


class AdminProviderSpecCreateIn(Schema):
    """新增一项服务商规格配置。"""

    provider_code: RoutingCode = Field(description="已存在的服务商编码", examples=["zheying"])
    spec_code: RoutingCode = Field(
        description="已存在的规格编码，同一服务商只能配置一次", examples=["gd_idcard"]
    )
    provider_item_id: str = Field(
        min_length=1, max_length=128, description="服务商侧的规格 ID", examples=["713"]
    )
    param_mapping: dict[str, str] = Field(
        default_factory=dict,
        description="办理字段到服务商字段名的映射，默认空对象",
        examples=[{"name": "text_name"}],
    )
    cost_fen: int = Field(ge=0, le=2_147_483_647, description="办理一次的成本，单位分", examples=[300])
    is_enabled: bool = Field(default=True, description="是否启用此服务商规格，默认启用", examples=[True])


class AdminProviderSpecUpdateIn(Schema):
    """修改服务商规格配置。省略字段保持原值。"""

    provider_code: RoutingCode | None = Field(
        default=None, description="新的服务商编码", examples=["zheying"]
    )
    spec_code: RoutingCode | None = Field(default=None, description="新的规格编码", examples=["gd_idcard"])
    provider_item_id: str | None = Field(
        default=None, min_length=1, max_length=128, description="新的服务商侧规格 ID", examples=["714"]
    )
    param_mapping: dict[str, str] | None = Field(
        default=None, description="新的办理字段映射，传空对象清空", examples=[{"name": "text_name"}]
    )
    cost_fen: int | None = Field(
        default=None, ge=0, le=2_147_483_647, description="新的办理成本，单位分", examples=[350]
    )
    is_enabled: bool | None = Field(default=None, description="是否启用此服务商规格", examples=[False])


class AdminRouteRuleCreateIn(Schema):
    """新增一条路由规则。"""

    provider_code: RoutingCode = Field(description="候选服务商编码", examples=["zheying"])
    spec_code: RoutingCode = Field(description="适用规格编码", examples=["gd_idcard"])
    region_code: RoutingRegionCode | None = Field(
        default=None, description="适用地区行政区划码，空值表示不限地区", examples=["440300"]
    )
    priority: int = Field(
        default=100,
        ge=-2_147_483_648,
        le=2_147_483_647,
        description="候选顺序，数字越小越优先，默认 100",
        examples=[10],
    )
    is_enabled: bool = Field(default=True, description="是否启用此规则，默认启用", examples=[True])


class AdminRouteRuleUpdateIn(Schema):
    """修改路由规则。省略字段保持原值。"""

    provider_code: RoutingCode | None = Field(
        default=None, description="新的候选服务商编码", examples=["zheying"]
    )
    spec_code: RoutingCode | None = Field(
        default=None, description="新的适用规格编码", examples=["gd_idcard"]
    )
    region_code: RoutingRegionCode | None = Field(
        default=None, description="新的行政区划码，显式传 null 改为不限地区", examples=[None]
    )
    priority: int | None = Field(
        default=None,
        ge=-2_147_483_648,
        le=2_147_483_647,
        description="新的优先级，数字越小越优先",
        examples=[20],
    )
    is_enabled: bool | None = Field(default=None, description="是否启用此规则", examples=[False])


# ---------- 审计日志 ----------


class AdminAuditLogOut(Schema):
    """一条后台操作审计日志。"""

    id: int = Field(description="日志 ID", examples=[501])
    admin_id: int = Field(description="操作人后台账号 ID", examples=[3])
    admin_username: str | None = Field(description="操作人用户名", examples=["fin_li"])
    action: str = Field(
        description="操作类型，如 refund.create、route_rule.update、provider_spec.create、admin_user.disable",
        examples=["refund.create"],
    )
    target_type: str = Field(
        description="操作对象类型，如 order、plan、provider_spec、route_rule、receipt_application、admin_user",
        examples=["order"],
    )
    target_id: int | None = Field(description="操作对象的内部 ID；没有具体对象为空", examples=[88])
    before: dict[str, Any] | None = Field(
        description="操作前的关键字段；新建和密码重置时为空",
        examples=[{"status": "paid", "refunded_fen": 0}],
    )
    after: dict[str, Any] | None = Field(
        description="操作后的关键字段；删除和密码重置时为空",
        examples=[{"status": "refunded", "refunded_fen": 3990}],
    )
    created_at: datetime = Field(description="操作时间（UTC，带时区）", examples=["2026-11-19T09:00:00Z"])


AdminAuditLogPage = page_model(AdminAuditLogOut, "AdminAuditLogPage")
