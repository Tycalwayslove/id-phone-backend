"""交易与权益：plans、plan_benefits、orders、order_items、payments、refunds、
entitlements、entitlement_quotas、entitlement_ledger。

金额一律用“分”存整数（price_fen = 1990 表示 19.9 元）。
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models._types import check_in
from app.models.base import Base, TimestampMixin

PLAN_STATUSES = ("draft", "on_sale", "off_sale")
# 新增一种权益类型 = 在这里加一个值 + 写对应的业务代码
BENEFIT_TYPES = (
    "storage_days",  # 保管天数
    "photo_scope",  # 1 = 单张照片，0 = 用户全部照片
    "receipt_quota",  # 可办回执次数（按成功出证计）
    "resubmit_limit",  # 每次回执被驳回后可免费重提次数
    "spec_change",  # 1 = 保管期内可无限改规格
    "one_person",  # 1 = 一卡一人
    "attach_to_parent",  # 1 = 加购项，到期时间跟随所属权益
)
ORDER_STATUSES = ("pending", "paid", "closed", "part_refunded", "refunded")
ITEM_TYPES = ("plan", "addon", "renew")
PAY_CHANNELS = ("wxpay", "alipay", "douyin_pay")
PAYMENT_STATUSES = ("pending", "success", "failed", "closed")
REFUND_STATUSES = ("pending", "success", "failed")
ENTITLEMENT_STATUSES = ("active", "expired", "revoked")
LEDGER_ACTIONS = ("reserve", "confirm", "release")


class Plan(TimestampMixin, Base):
    """套餐。价格和状态在这里，具体给什么权益在 plan_benefits 里。"""

    __tablename__ = "plans"
    __table_args__ = (
        check_in("status", PLAN_STATUSES, "status_valid"),
        CheckConstraint("price_fen >= 0", name="price_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    price_fen: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    sale_starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sale_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sort: Mapped[int] = mapped_column(Integer, server_default="0")
    display: Mapped[dict] = mapped_column(JSONB, server_default="{}")


class PlanBenefit(TimestampMixin, Base):
    __tablename__ = "plan_benefits"
    __table_args__ = (
        UniqueConstraint("plan_id", "benefit_type", name="uq_plan_benefits_plan_type"),
        check_in("benefit_type", BENEFIT_TYPES, "benefit_type_valid"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("plans.id", ondelete="CASCADE")
    )  # 联合唯一约束以 plan_id 开头，已经能当索引用
    benefit_type: Mapped[str] = mapped_column(Text)
    int_value: Mapped[int] = mapped_column(Integer)


class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        check_in("status", ORDER_STATUSES, "status_valid"),
        CheckConstraint(
            "total_fen >= 0 AND paid_fen >= 0 AND refunded_fen >= 0 AND refunded_fen <= paid_fen",
            name="amounts_valid",
        ),
        Index("ix_orders_user_created", "user_id", "created_at"),
        Index(
            "ix_orders_pending_expire",
            "expire_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    order_no: Mapped[str] = mapped_column(Text, unique=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    channel_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("channels.id", ondelete="SET NULL"), index=True
    )
    total_fen: Mapped[int] = mapped_column(Integer)
    paid_fen: Mapped[int] = mapped_column(Integer, server_default="0")
    refunded_fen: Mapped[int] = mapped_column(Integer, server_default="0")
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    client: Mapped[str] = mapped_column(Text)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrderItem(TimestampMixin, Base):
    """业务子单。二期冲印、三期 3D 手办各自加一个 item_type 和一张详情表。"""

    __tablename__ = "order_items"
    __table_args__ = (
        check_in("item_type", ITEM_TYPES, "item_type_valid"),
        CheckConstraint(
            "quantity > 0 AND unit_price_fen >= 0 AND amount_fen >= 0",
            name="amounts_valid",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="RESTRICT"), index=True
    )
    item_type: Mapped[str] = mapped_column(Text)
    plan_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("plans.id", ondelete="RESTRICT"), index=True
    )
    photo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("photos.id", ondelete="RESTRICT"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, server_default="1")
    unit_price_fen: Mapped[int] = mapped_column(Integer)
    amount_fen: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSONB, server_default="{}")


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        check_in("channel", PAY_CHANNELS, "channel_valid"),
        check_in("status", PAYMENT_STATUSES, "status_valid"),
        CheckConstraint("amount_fen > 0", name="amount_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="RESTRICT"), index=True
    )
    channel: Mapped[str] = mapped_column(Text)
    out_trade_no: Mapped[str] = mapped_column(Text, unique=True)
    transaction_id: Mapped[str | None] = mapped_column(Text, unique=True)
    amount_fen: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    raw: Mapped[dict | None] = mapped_column(JSONB)


class Refund(TimestampMixin, Base):
    __tablename__ = "refunds"
    __table_args__ = (
        check_in("status", REFUND_STATUSES, "status_valid"),
        CheckConstraint("amount_fen > 0", name="amount_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    payment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("payments.id", ondelete="RESTRICT"), index=True
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="RESTRICT"), index=True
    )
    out_refund_no: Mapped[str] = mapped_column(Text, unique=True)
    amount_fen: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    operator: Mapped[str] = mapped_column(Text)  # system 或后台账号名
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Entitlement(TimestampMixin, Base):
    """权益：每次购买生成一条，续费也是新的一条，不改旧行。"""

    __tablename__ = "entitlements"
    __table_args__ = (
        check_in("status", ENTITLEMENT_STATUSES, "status_valid"),
        CheckConstraint("ends_at > starts_at", name="period_valid"),
        Index("ix_entitlements_user_ends", "user_id", "ends_at"),
        Index(
            "ix_entitlements_active_ends",
            "ends_at",
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    order_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("order_items.id", ondelete="RESTRICT"), unique=True
    )
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("plans.id", ondelete="RESTRICT"), index=True)
    # 为空 = 覆盖该用户全部照片（99 元档）
    photo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("photos.id", ondelete="RESTRICT"), index=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    benefits_snapshot: Mapped[dict] = mapped_column(JSONB)
    # 一卡一人：首次办理回执时写入，之后只能为同一身份证号办理
    bound_idcard_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")


class EntitlementQuota(TimestampMixin, Base):
    """权益里可以计数的额度，比如回执次数。total 是总数，used 是已用。"""

    __tablename__ = "entitlement_quotas"
    __table_args__ = (
        UniqueConstraint("entitlement_id", "benefit_type", name="uq_entitlement_quotas_ent_type"),
        check_in("benefit_type", BENEFIT_TYPES, "benefit_type_valid"),
        CheckConstraint("used >= 0 AND used <= total", name="used_within_total"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    entitlement_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entitlements.id", ondelete="RESTRICT")
    )
    benefit_type: Mapped[str] = mapped_column(Text)
    total: Mapped[int] = mapped_column(Integer)
    used: Mapped[int] = mapped_column(Integer, server_default="0")


class EntitlementLedger(TimestampMixin, Base):
    """额度流水：每次占用、确认、退还都记一笔。唯一约束保证同一申请同一动作只发生一次。"""

    __tablename__ = "entitlement_ledger"
    __table_args__ = (
        UniqueConstraint("quota_id", "action", "application_id", name="uq_entitlement_ledger_once"),
        check_in("action", LEDGER_ACTIONS, "action_valid"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    quota_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entitlement_quotas.id", ondelete="RESTRICT")
    )
    application_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("receipt_applications.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[str] = mapped_column(Text)
    delta: Mapped[int] = mapped_column(Integer)
