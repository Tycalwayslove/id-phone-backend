"""接口依赖：数据库会话、当前用户、当前后台账号、权限点、分页参数。"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Header, Query, Request
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import AppError, ErrorCode
from app.core.security import hash_token, sign
from app.core.utils import utcnow
from app.models import AdminSession, AdminUser, AuthSession, User

DB = Annotated[Session, Depends(get_db)]

_bearer = HTTPBearer(auto_error=False, description="小程序登录后拿到的令牌：Authorization: Bearer <token>")
_admin_cookie = APIKeyCookie(name="admin_session", auto_error=False, description="后台登录后写入的 Cookie")

# 每次使用最多每小时写一次库，避免每个请求都更新会话
_TOUCH_INTERVAL = timedelta(hours=1)


@dataclass
class CurrentUser:
    id: int
    session_id: int
    user: User


def _load_user_session(db: Session, token: str) -> CurrentUser:
    now = utcnow()
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if (
        session is None
        or session.revoked_at is not None
        or session.expires_at <= now
        or session.absolute_expires_at <= now
    ):
        raise AppError(ErrorCode.AUTH_INVALID)
    user = db.get(User, session.user_id)
    if user is None or user.status == "cancelled":
        raise AppError(ErrorCode.AUTH_INVALID)
    if user.status == "disabled":
        raise AppError(ErrorCode.ACCOUNT_DISABLED)
    if now - session.last_seen_at >= _TOUCH_INTERVAL:
        session.last_seen_at = now
        session.expires_at = min(
            now + timedelta(days=settings.session_idle_days), session.absolute_expires_at
        )
        user.last_active_at = now
        db.commit()
    return CurrentUser(id=user.id, session_id=session.id, user=user)


def current_user(
    db: DB, cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> CurrentUser:
    if cred is None or not cred.credentials:
        raise AppError(ErrorCode.AUTH_REQUIRED)
    return _load_user_session(db, cred.credentials)


def optional_user(
    db: DB, cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> CurrentUser | None:
    if cred is None or not cred.credentials:
        return None
    return _load_user_session(db, cred.credentials)


Me = Annotated[CurrentUser, Depends(current_user)]
MaybeMe = Annotated[CurrentUser | None, Depends(optional_user)]


# ---------- 后台 ----------

# 全部权限点。新增权限点先加在这里，再分配给角色；owner 拥有全部
ALL_PERMISSIONS: set[str] = {
    "user:read",
    "order:read",
    "refund:create",
    "application:read",
    "application:operate",
    "plan:read",
    "plan:write",
    "spec:read",
    "spec:write",
    "provider:read",
    "provider:write",
    "audit:read",
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "owner": {"*"},
    "operator": {
        "user:read",
        "order:read",
        "application:read",
        "application:operate",
        "plan:read",
        "spec:read",
        "spec:write",
        "provider:read",
        "audit:read",
    },
    "finance": {"user:read", "order:read", "refund:create", "plan:read", "audit:read"},
}


@dataclass
class CurrentAdmin:
    id: int
    username: str
    role: str
    session_id: int

    def can(self, permission: str) -> bool:
        perms = ROLE_PERMISSIONS.get(self.role, set())
        return "*" in perms or permission in perms


def csrf_for(token_hash: str) -> str:
    return sign(f"csrf:{token_hash}")


def current_admin(
    request: Request,
    db: DB,
    token: Annotated[str | None, Depends(_admin_cookie)],
    x_csrf_token: Annotated[
        str | None, Header(description="修改类请求必须带上登录时返回的 csrf_token，防止跨站请求伪造")
    ] = None,
) -> CurrentAdmin:
    if not token:
        raise AppError(ErrorCode.AUTH_REQUIRED)
    now = utcnow()
    th = hash_token(token)
    session = db.scalar(select(AdminSession).where(AdminSession.token_hash == th))
    if (
        session is None
        or session.revoked_at is not None
        or session.expires_at <= now
        or session.absolute_expires_at <= now
    ):
        raise AppError(ErrorCode.AUTH_INVALID)
    admin = db.get(AdminUser, session.admin_id)
    if admin is None or admin.status != "active":
        raise AppError(ErrorCode.AUTH_INVALID)
    if request.method not in ("GET", "HEAD", "OPTIONS") and x_csrf_token != csrf_for(th):
        raise AppError(ErrorCode.PERMISSION_DENIED, "缺少或错误的 X-CSRF-Token")
    if now - session.last_seen_at >= timedelta(minutes=5):
        session.last_seen_at = now
        session.expires_at = min(
            now + timedelta(hours=settings.admin_session_idle_hours), session.absolute_expires_at
        )
        db.commit()
    return CurrentAdmin(id=admin.id, username=admin.username, role=admin.role, session_id=session.id)


Admin = Annotated[CurrentAdmin, Depends(current_admin)]


def require(permission: str):
    """路由上写 Depends(require("refund:create"))，没有这个权限点就返回 403。"""

    def _check(admin: Admin) -> CurrentAdmin:
        if not admin.can(permission):
            raise AppError(ErrorCode.PERMISSION_DENIED)
        return admin

    return _check


# ---------- 通用参数 ----------


@dataclass
class PageParams:
    cursor: str | None
    limit: int


def page_params(
    cursor: Annotated[
        str | None, Query(description="翻页游标：第一页不传，之后传上一页返回的 next_cursor")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="每页条数，1～100，默认 20")] = 20,
) -> PageParams:
    return PageParams(cursor=cursor, limit=limit)


Page = Annotated[PageParams, Depends(page_params)]

IdempotencyKeyHeader = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        description="防重复提交：客户端为每次操作生成一个随机串（如 UUID），网络重试时带同一个值，服务端只处理一次",
        max_length=128,
    ),
]
