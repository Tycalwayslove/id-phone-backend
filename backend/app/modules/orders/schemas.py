"""套餐、订单、支付通知的请求与返回模型。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.core.schemas import Schema, page_model


class PlanBenefitsOut(Schema):
    """套餐包含的权益。套餐没有某项权益时，该项为 0。"""

    storage_days: int = Field(
        default=0, description="照片保管天数，从付款成功起算；0 表示套餐不含保管期", examples=[365]
    )
    photo_scope: int = Field(
        default=0,
        description="权益覆盖的照片范围：1 = 只覆盖下单时选的一张照片；0 = 覆盖用户全部照片",
        examples=[1],
    )
    receipt_quota: int = Field(default=0, description="可办理回执的次数；0 表示不含回执", examples=[1])
    resubmit_limit: int = Field(default=0, description="回执被驳回后可免费重新提交的次数", examples=[3])
    spec_change: int = Field(
        default=0, description="保管期内能否无限更换规格：1 = 可以，0 = 不可以", examples=[1]
    )
    one_person: int = Field(
        default=0, description="是否一卡一人：1 = 首次办回执后只能给同一个人办，0 = 不限制", examples=[0]
    )
    attach_to_parent: int = Field(
        default=0,
        description="是否加购项：1 = 加购项，下单时必须选一个已有权益作为主权益，到期时间跟主权益一致；0 = 独立套餐",
        examples=[0],
    )


class PlanOut(Schema):
    """在售套餐。"""

    code: str = Field(description="套餐编码，下单时传这个值", examples=["photo_year_39_9"])
    name: str = Field(description="套餐名称，可直接展示", examples=["单张照片年度保管"])
    price_fen: int = Field(description="价格，单位：分（3990 表示 39.9 元）", examples=[3990])
    benefits: PlanBenefitsOut = Field(description="套餐包含的权益")
    display: dict[str, Any] = Field(
        description="展示用的配置（卖点文案、角标等），由运营后台配置，原样返回；没有配置时为空对象",
        examples=[{"badge": "推荐", "points": ["期内无限下载", "被驳回免费重提"]}],
    )


class OrderCreateIn(Schema):
    """下单请求。"""

    plan_code: str = Field(
        min_length=1,
        max_length=64,
        description="要购买的套餐编码，来自套餐列表",
        examples=["photo_year_39_9"],
    )
    photo_id: int | None = Field(
        default=None,
        gt=0,
        description="要保管/办理的照片 ID，必须是本人的照片。照片范围为“单张”的套餐必填；其他套餐可不传",
        examples=[101],
    )
    parent_entitlement_id: int | None = Field(
        default=None,
        gt=0,
        description="主权益 ID，必须是本人当前有效的权益。只有加购项套餐（如加办回执）必填，其他套餐不用传",
        examples=[12],
    )


class OrderItemOut(Schema):
    """订单里的一个商品项。"""

    item_type: Literal["plan", "addon", "renew"] = Field(
        description="类型：plan = 套餐；addon = 加购项（跟随主权益）；renew = 续费", examples=["plan"]
    )
    plan_code: str | None = Field(description="套餐编码；没有关联套餐时为空", examples=["photo_year_39_9"])
    plan_name: str | None = Field(
        description="套餐名称（下单时的名称）；没有关联套餐时为空", examples=["单张照片年度保管"]
    )
    photo_id: int | None = Field(description="关联的照片 ID；不针对某张照片时为空", examples=[101])
    amount_fen: int = Field(description="这一项的金额，单位：分", examples=[3990])


class OrderOut(Schema):
    """订单。"""

    order_no: str = Field(description="订单号，对外展示和查询用", examples=["O20261119083012A1B2C3"])
    status: Literal["pending", "paid", "closed", "part_refunded", "refunded"] = Field(
        description=(
            "订单状态：pending = 待支付；paid = 已支付；closed = 已关闭（超时未支付或用户取消）；"
            "part_refunded = 部分退款；refunded = 已全额退款"
        ),
        examples=["pending"],
    )
    total_fen: int = Field(description="订单应付金额，单位：分", examples=[3990])
    paid_fen: int = Field(description="已支付金额，单位：分；未支付为 0", examples=[0])
    refunded_fen: int = Field(description="已退款金额，单位：分；没有退款为 0", examples=[0])
    created_at: datetime = Field(description="下单时间（带时区）", examples=["2026-11-19T08:30:12Z"])
    paid_at: datetime | None = Field(
        description="支付成功时间（带时区）；未支付时为空", examples=["2026-11-19T08:31:00Z"]
    )
    expire_at: datetime = Field(
        description="支付截止时间（带时区），超过后订单自动关闭，需要重新下单",
        examples=["2026-11-19T09:00:12Z"],
    )
    items: list[OrderItemOut] = Field(description="订单商品项")


class OrderCreatedOut(OrderOut):
    """下单结果：订单信息加上拉起支付的参数。"""

    pay_params: dict[str, Any] = Field(
        description=(
            "拉起微信支付所需的参数。真实支付时是 wx.requestPayment 需要的 timeStamp、nonceStr、package、signType、paySign；"
            '联调（fake）模式下为 {"mode": "fake", ...}，前端看到 mode=fake 时不要调 wx.requestPayment，'
            "改调模拟支付接口 POST /api/v1/dev/orders/{order_no}/simulate-paid"
        ),
        examples=[{"mode": "fake", "out_trade_no": "P20261119083012A1B2C3", "amount_fen": 3990}],
    )


OrderPage = page_model(OrderOut, "OrderPage")


class WxpayFailure(Schema):
    """微信支付通知处理失败时的应答。"""

    code: Literal["FAIL"] = Field(description="固定为 FAIL，表示通知处理失败", examples=["FAIL"])
    message: str = Field(description="通知处理失败的原因", examples=["支付通知签名不正确"])
