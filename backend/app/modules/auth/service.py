from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.utils import utcnow
from app.integrations.wechat import WechatSession, get_wechat
from app.models import AuthSession, User, UserIdentity
from app.modules.auth import repo
from app.modules.auth.schemas import LoginResponse, LoginUserOut

PROVIDER = "wx_mini"
CLIENT = "wx_mini"


def _phone_masked(user: User) -> str | None:
    if not user.phone_enc:
        return None
    return security.mask_phone(security.decrypt(user.phone_enc, "phone"))


def _new_user(db: Session, source_app_id: int) -> User:
    user = User(status="active", source_app_id=source_app_id)
    db.add(user)
    db.flush()
    return user


def _resolve_user(db: Session, ws: WechatSession) -> tuple[User, UserIdentity, bool]:
    """找到或创建 (用户, 身份)，第三项表示用户是否本次新建。"""
    source_app_id = repo.ensure_client_app(db, platform=repo.client_app_platform(PROVIDER), app_id=ws.app_id)
    identity = repo.get_identity(db, PROVIDER, ws.app_id, ws.open_id)
    if identity is not None:
        user = db.get(User, identity.user_id)
        if user is not None and user.status != "cancelled":
            if user.status == "disabled":
                raise AppError(ErrorCode.ACCOUNT_DISABLED)
            if ws.union_id and identity.union_id != ws.union_id:
                identity.union_id = ws.union_id
            return user, identity, False
        # 已注销：当作不存在，新建用户并把身份指向新用户
        user = _new_user(db, source_app_id)
        identity.user_id = user.id
        identity.union_id = ws.union_id
        db.flush()
        return user, identity, True

    user = repo.find_live_user_by_union(db, ws.union_id) if ws.union_id else None
    is_new = user is None
    if user is None:
        user = _new_user(db, source_app_id)
    elif user.status == "disabled":
        raise AppError(ErrorCode.ACCOUNT_DISABLED)
    identity = UserIdentity(
        user_id=user.id, provider=PROVIDER, app_id=ws.app_id, open_id=ws.open_id, union_id=ws.union_id
    )
    db.add(identity)
    db.flush()
    return user, identity, is_new


def wechat_mini_login(db: Session, *, code: str, user_agent: str | None, ip: str | None) -> LoginResponse:
    ws = get_wechat().code2session(code)
    try:
        user, identity, is_new = _resolve_user(db, ws)
    except IntegrityError:
        # 并发的首次登录抢着建了同一个身份：回滚后按已存在处理
        db.rollback()
        user, identity, is_new = _resolve_user(db, ws)

    now = utcnow()
    token = security.new_token()
    session = AuthSession(
        user_id=user.id,
        identity_id=identity.id,
        token_hash=security.hash_token(token),
        client=CLIENT,
        user_agent=user_agent[:500] if user_agent else None,
        ip=ip,
        last_seen_at=now,
        expires_at=now + timedelta(days=settings.session_idle_days),
        absolute_expires_at=now + timedelta(days=settings.session_absolute_days),
    )
    db.add(session)
    user.last_active_at = now
    db.commit()
    return LoginResponse(
        token=token,
        expires_at=session.expires_at,
        user=LoginUserOut(
            id=user.id,
            nickname=user.nickname,
            avatar_url=user.avatar_url,
            phone_masked=_phone_masked(user),
            is_new=is_new,
        ),
    )


def logout(db: Session, *, session_id: int) -> None:
    session = repo.get_session(db, session_id)
    if session is not None and session.revoked_at is None:
        session.revoked_at = utcnow()
    db.commit()


def revoke_all_for_user(db: Session, user_id: int) -> int:
    """吊销该用户全部会话，返回数量。不 commit，由调用方统一提交。"""
    return repo.revoke_all(db, user_id)
