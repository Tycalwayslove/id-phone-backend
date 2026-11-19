"""通知与后台：notify_tasks、admin_users、audit_logs。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models._types import check_in
from app.models.base import Base, TimestampMixin

NOTIFY_EVENTS = (
    "receipt_rejected",
    "receipt_completed",
    "entitlement_expiring",
    "receipt_expiring",
)
NOTIFY_CHANNELS = ("mini_subscribe", "mp_template", "wecom", "sms", "voice", "manual_call")
NOTIFY_STATUSES = ("pending", "sent", "failed", "skipped", "cancelled")
ADMIN_ROLES = ("owner", "operator", "finance")
ADMIN_STATUSES = ("active", "disabled")


class NotifyTask(TimestampMixin, Base):
    """一条待发或已发的通知。驳回升级通知 = 同一事件的 step 1、2、3…"""

    __tablename__ = "notify_tasks"
    __table_args__ = (
        check_in("event", NOTIFY_EVENTS, "event_valid"),
        check_in("channel", NOTIFY_CHANNELS, "channel_valid"),
        check_in("status", NOTIFY_STATUSES, "status_valid"),
        # 申请和权益二选一，恰好一个不为空
        CheckConstraint("num_nonnulls(application_id, entitlement_id) = 1", name="one_target"),
        Index(
            "uq_notify_tasks_once",
            "application_id",
            "entitlement_id",
            "event",
            "step",
            "channel",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "ix_notify_tasks_pending",
            "scheduled_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    application_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("receipt_applications.id", ondelete="CASCADE"), index=True
    )
    entitlement_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("entitlements.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[str] = mapped_column(Text)
    step: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    channel: Mapped[str] = mapped_column(Text)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    result: Mapped[dict | None] = mapped_column(JSONB)


class AdminUser(TimestampMixin, Base):
    __tablename__ = "admin_users"
    __table_args__ = (
        check_in("role", ADMIN_ROLES, "role_valid"),
        check_in("status", ADMIN_STATUSES, "status_valid"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")


class AuditLog(TimestampMixin, Base):
    """后台操作审计。target_type + target_id 可以指向任意对象，所以这里不加外键。"""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_target", "target_type", "target_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    admin_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("admin_users.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
