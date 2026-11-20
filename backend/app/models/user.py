"""用户与私域：users、user_identities、client_apps、channels、wecom_contacts、user_tags。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    LargeBinary,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models._types import check_in
from app.models.base import Base, TimestampMixin

USER_STATUSES = ("active", "disabled", "cancelled")
IDENTITY_PROVIDERS = ("wx_mini", "wx_mp", "alipay_mini", "douyin_mini", "h5")
CLIENT_APP_PLATFORMS = ("wx_mini", "wx_mp", "alipay_mini", "douyin_mini", "web")
CLIENT_APP_STATUSES = ("active", "disabled")
TAG_SOURCES = ("auto", "manual", "wecom")


class Channel(TimestampMixin, Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(Text)


class ClientApp(TimestampMixin, Base):
    """首次注册来源的客户端应用，由登录登记，名称和状态由运营维护。"""

    __tablename__ = "client_apps"
    __table_args__ = (
        UniqueConstraint("platform", "app_id", name="uq_client_apps_platform_app_id"),
        check_in("platform", CLIENT_APP_PLATFORMS, "platform_valid"),
        check_in("status", CLIENT_APP_STATUSES, "status_valid"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    platform: Mapped[str] = mapped_column(Text)
    app_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (check_in("status", USER_STATUSES, "status_valid"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    nickname: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    phone_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    phone_hash: Mapped[str | None] = mapped_column(Text, unique=True)
    first_channel_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("channels.id", ondelete="SET NULL"), index=True
    )
    source_app_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("client_apps.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(Text, server_default="active")
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserIdentity(TimestampMixin, Base):
    """一个用户在某个端上的身份。同一个人在小程序、公众号、支付宝各有一行。"""

    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("provider", "app_id", "open_id", name="uq_user_identities_provider_app_open"),
        check_in("provider", IDENTITY_PROVIDERS, "provider_valid"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(Text)
    app_id: Mapped[str] = mapped_column(Text)
    open_id: Mapped[str] = mapped_column(Text)
    union_id: Mapped[str | None] = mapped_column(Text, index=True)
    # 小程序一次性订阅消息的剩余授权次数，按模板 ID 记：{"tmpl_xxx": 2}
    subscribe_quota: Mapped[dict] = mapped_column(JSONB, server_default="{}")


class WecomContact(TimestampMixin, Base):
    """企业微信外部联系人。加好友时先存，认出是哪个用户后再填 user_id。"""

    __tablename__ = "wecom_contacts"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    external_userid: Mapped[str] = mapped_column(Text, unique=True)
    follow_userid: Mapped[str] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    union_id: Mapped[str | None] = mapped_column(Text, index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserTag(TimestampMixin, Base):
    __tablename__ = "user_tags"
    __table_args__ = (check_in("source", TAG_SOURCES, "source_valid"),)

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tag_key: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text, server_default="auto")
