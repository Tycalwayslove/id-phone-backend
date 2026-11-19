"""规格与供应链：specs、providers、provider_specs、route_rules。"""

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
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models._types import check_in
from app.models.base import Base, TimestampMixin

SPEC_CATEGORIES = ("receipt", "normal", "exam")
SPEC_STATUSES = ("active", "inactive")
PROVIDER_STATUSES = ("enabled", "disabled", "circuit_open")


class Spec(TimestampMixin, Base):
    """规格库。父子结构：广东身份证（父）下挂深圳市、广州市（子）。"""

    __tablename__ = "specs"
    __table_args__ = (
        check_in("category", SPEC_CATEGORIES, "category_valid"),
        check_in("status", SPEC_STATUSES, "status_valid"),
        CheckConstraint("beauty_max BETWEEN 0 AND 5", name="beauty_max_range"),
        CheckConstraint("width_px > 0 AND height_px > 0", name="size_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("specs.id", ondelete="RESTRICT"), index=True
    )
    category: Mapped[str] = mapped_column(Text)
    cert_type: Mapped[str] = mapped_column(Text)
    region_code: Mapped[str | None] = mapped_column(Text)  # 行政区划码，空 = 不限地区
    width_px: Mapped[int] = mapped_column(Integer)
    height_px: Mapped[int] = mapped_column(Integer)
    width_mm: Mapped[int | None] = mapped_column(Integer)
    height_mm: Mapped[int | None] = mapped_column(Integer)
    dpi: Mapped[int] = mapped_column(Integer, server_default="300")
    bg_colors: Mapped[list] = mapped_column(JSONB, server_default="[]")
    file_size_min_kb: Mapped[int | None] = mapped_column(Integer)
    file_size_max_kb: Mapped[int | None] = mapped_column(Integer)
    beauty_max: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    # 办理时要用户填的字段，如 [{"key": "mobile", "label": "手机号", "required": true}]
    form_schema: Mapped[list] = mapped_column(JSONB, server_default="[]")
    official_valid_days: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    sort: Mapped[int] = mapped_column(Integer, server_default="0")


class Provider(TimestampMixin, Base):
    __tablename__ = "providers"
    __table_args__ = (check_in("status", PROVIDER_STATUSES, "status_valid"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    adapter: Mapped[str] = mapped_column(Text)  # 代码里的适配器名
    config_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # 密钥等，加密后存
    # 接口完全相同、疑似同一上游的服务商填同一个值，自动切换时不互为备份
    upstream_group: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="enabled")


class ProviderSpec(TimestampMixin, Base):
    """覆盖矩阵：哪家服务商能办哪个规格、对方规格 ID 是什么、成本多少。"""

    __tablename__ = "provider_specs"
    __table_args__ = (
        UniqueConstraint("provider_id", "spec_id", name="uq_provider_specs_provider_spec"),
        CheckConstraint("cost_fen >= 0", name="cost_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    provider_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("providers.id", ondelete="CASCADE"))
    spec_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("specs.id", ondelete="CASCADE"), index=True)
    provider_item_id: Mapped[str] = mapped_column(Text)
    param_mapping: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    cost_fen: Mapped[int] = mapped_column(Integer)
    is_enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RouteRule(TimestampMixin, Base):
    """路由规则：一行是一个候选服务商，按 priority 从小到大选。"""

    __tablename__ = "route_rules"
    __table_args__ = (
        # region_code 为空表示“不限地区”；NULLS NOT DISTINCT 让两个空值也算重复
        Index(
            "uq_route_rules_spec_region_provider",
            "spec_id",
            "region_code",
            "provider_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    spec_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("specs.id", ondelete="CASCADE"))
    provider_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("providers.id", ondelete="CASCADE"), index=True
    )
    region_code: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, server_default="100")
    is_enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
