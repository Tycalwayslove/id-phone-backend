"""照片资产：files、photos、photo_renders、share_links。

OSS 命名规则（见文档「数据库设计」第四节 4）：
{环境}/u{用户ID}/{p照片ID 或 a申请ID}/{类型}[_{规格code}_{底色}_b{美化档位}]_f{文件ID}.{扩展名}
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
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models._types import check_in
from app.models.base import Base, TimestampMixin

FILE_KINDS = ("original", "matting", "preview", "render", "receipt")
FILE_STATUSES = ("active", "purged")
PHOTO_SOURCES = ("camera", "upload")
PHOTO_STATUSES = ("draft", "active", "expired", "purged")


class File(TimestampMixin, Base):
    """OSS 上的每个文件在这里登记一行；业务表只存 file_id，不直接存路径。"""

    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("bucket", "storage_key", name="uq_files_bucket_key"),
        check_in("kind", FILE_KINDS, "kind_valid"),
        check_in("status", FILE_STATUSES, "status_valid"),
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
        Index("ix_files_user_kind", "user_id", "kind"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(Text)
    bucket: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Photo(TimestampMixin, Base):
    """底片：原图 + 抠好的人像层 + 美化参数。改规格就是用它重新导出。"""

    __tablename__ = "photos"
    __table_args__ = (
        check_in("source", PHOTO_SOURCES, "source_valid"),
        check_in("status", PHOTO_STATUSES, "status_valid"),
        Index("ix_photos_user_created", "user_id", "created_at"),
        Index(
            "ix_photos_retain_until_live",
            "retain_until",
            postgresql_where=text("status <> 'purged'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    source: Mapped[str] = mapped_column(Text)
    original_file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("files.id", ondelete="RESTRICT"), unique=True
    )
    matting_file_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("files.id", ondelete="SET NULL"), unique=True
    )
    beauty_params: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    check_result: Mapped[dict | None] = mapped_column(JSONB)
    # 冗余：覆盖这张照片的权益中最晚的 ends_at；未付费为空
    access_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # access_until + 180 天，过了就删 OSS 文件
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default="draft")


class PhotoRender(TimestampMixin, Base):
    """导出图：同一张底片按某个规格、底色、美化档位导出的结果。参数相同就复用。"""

    __tablename__ = "photo_renders"
    __table_args__ = (
        UniqueConstraint(
            "photo_id",
            "spec_id",
            "bg_color",
            "beauty_level",
            "watermarked",
            name="uq_photo_renders_variant",
        ),
        CheckConstraint("beauty_level BETWEEN 0 AND 5", name="beauty_level_range"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    photo_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("photos.id", ondelete="RESTRICT")
    )  # 联合唯一约束以 photo_id 开头，已经能当索引用
    spec_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("specs.id", ondelete="RESTRICT"), index=True)
    file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("files.id", ondelete="RESTRICT"), unique=True)
    bg_color: Mapped[str] = mapped_column(Text)
    beauty_level: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    watermarked: Mapped[bool] = mapped_column(Boolean)


class ShareLink(TimestampMixin, Base):
    __tablename__ = "share_links"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    render_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("photo_renders.id", ondelete="CASCADE"), index=True
    )
    token: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_downloads: Mapped[int | None] = mapped_column(Integer)
    download_count: Mapped[int] = mapped_column(Integer, server_default="0")
