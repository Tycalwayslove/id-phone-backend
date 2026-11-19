from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.utils import utcnow
from app.models import AuthSession, User, UserIdentity


def get_identity(db: Session, provider: str, app_id: str, open_id: str) -> UserIdentity | None:
    return db.scalar(
        select(UserIdentity).where(
            UserIdentity.provider == provider,
            UserIdentity.app_id == app_id,
            UserIdentity.open_id == open_id,
        )
    )


def find_live_user_by_union(db: Session, union_id: str) -> User | None:
    """按 union_id 找已有的、未注销的用户（取最早创建的）。"""
    return db.scalar(
        select(User)
        .join(UserIdentity, UserIdentity.user_id == User.id)
        .where(UserIdentity.union_id == union_id, User.status != "cancelled")
        .order_by(User.id)
        .limit(1)
    )


def get_session(db: Session, session_id: int) -> AuthSession | None:
    return db.get(AuthSession, session_id)


def revoke_all(db: Session, user_id: int) -> int:
    """把该用户所有未吊销的会话标记吊销，返回数量。"""
    res = db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    return res.rowcount or 0
