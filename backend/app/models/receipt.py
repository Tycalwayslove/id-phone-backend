"""回执履约：receipt_applications、receipt_attempts、provider_callbacks。

两层结构：
- 申请（application）：用户看到的“一单”，一次办理一条。
- 提交记录（attempt）：每次发给服务商一行。驳回后重提、换服务商重提，都是同一申请下的新提交记录。
  同一申请任何时刻只有一条 is_current = true，只有它的回调能改申请状态；旧提交晚到的回调只记录不覆盖。
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models._types import check_in
from app.models.base import Base, TimestampMixin

APPLICATION_STATUSES = (
    "pending",
    "processing",
    "rejected",
    "completed",
    "failed",
    "cancelled",
)
ATTEMPT_STATUSES = (
    "created",
    "submitted",
    "unknown",
    "processing",
    "completed",
    "rejected",
    "failed",
    "abandoned",
)
CALLBACK_RESULTS = ("pending", "applied", "stale", "duplicate", "unmatched", "error")


class ReceiptApplication(TimestampMixin, Base):
    __tablename__ = "receipt_applications"
    __table_args__ = (
        check_in("status", APPLICATION_STATUSES, "status_valid"),
        CheckConstraint("resubmit_count >= 0", name="resubmit_count_non_negative"),
        Index("ix_receipt_applications_user_created", "user_id", "created_at"),
        Index("ix_receipt_applications_status_updated", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    app_no: Mapped[str] = mapped_column(Text, unique=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    # 当前照片：驳回后换照片重提会更新；每次提交用的照片记在提交记录上
    photo_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("photos.id", ondelete="RESTRICT"), index=True
    )
    spec_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("specs.id", ondelete="RESTRICT"), index=True)
    entitlement_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entitlements.id", ondelete="RESTRICT"), index=True
    )
    region_code: Mapped[str | None] = mapped_column(Text)
    form_data_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # 姓名、身份证号等，加密后存
    idcard_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    resubmit_count: Mapped[int] = mapped_column(Integer, server_default="0")
    reject_reason: Mapped[str | None] = mapped_column(Text)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    image_code: Mapped[str | None] = mapped_column(Text)  # 图像号
    receipt_file_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("files.id", ondelete="SET NULL"), unique=True
    )
    official_expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReceiptAttempt(TimestampMixin, Base):
    __tablename__ = "receipt_attempts"
    __table_args__ = (
        UniqueConstraint("application_id", "seq", name="uq_receipt_attempts_app_seq"),
        UniqueConstraint("provider_id", "provider_order_no", name="uq_receipt_attempts_provider_order"),
        check_in("status", ATTEMPT_STATUSES, "status_valid"),
        CheckConstraint("seq >= 1", name="seq_positive"),
        CheckConstraint("cost_fen IS NULL OR cost_fen >= 0", name="cost_non_negative"),
        # 同一申请只能有一条当前提交
        Index(
            "uq_receipt_attempts_one_current",
            "application_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        # 补偿轮询只扫还没结果的提交
        Index(
            "ix_receipt_attempts_poll",
            "next_poll_at",
            postgresql_where=text("status IN ('submitted', 'unknown', 'processing')"),
        ),
        Index("ix_receipt_attempts_provider_finished", "provider_id", "finished_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    application_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("receipt_applications.id", ondelete="RESTRICT")
    )
    seq: Mapped[int] = mapped_column(Integer)
    provider_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("providers.id", ondelete="RESTRICT"))
    render_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("photo_renders.id", ondelete="RESTRICT"), index=True
    )
    provider_order_no: Mapped[str | None] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, server_default="true")
    status: Mapped[str] = mapped_column(Text, server_default="created")
    reject_reason: Mapped[str | None] = mapped_column(Text)
    cost_fen: Mapped[int | None] = mapped_column(Integer)
    request_payload: Mapped[dict | None] = mapped_column(JSONB)  # 敏感字段脱敏后存
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderCallback(TimestampMixin, Base):
    """服务商回调原文。先存再处理，dedupe_key 挡住重复回调。"""

    __tablename__ = "provider_callbacks"
    __table_args__ = (check_in("process_result", CALLBACK_RESULTS, "process_result_valid"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("providers.id", ondelete="RESTRICT"), index=True
    )
    attempt_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("receipt_attempts.id", ondelete="RESTRICT"), index=True
    )
    provider_order_no: Mapped[str | None] = mapped_column(Text)
    event_status: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB)
    signature_ok: Mapped[bool] = mapped_column(Boolean)
    dedupe_key: Mapped[str] = mapped_column(Text, unique=True)
    process_result: Mapped[str] = mapped_column(Text, server_default="pending")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
