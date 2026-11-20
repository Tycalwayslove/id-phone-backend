from cryptography.exceptions import InvalidTag
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import security
from app.core.errors import AppError, ErrorCode
from app.integrations.wechat import get_wechat
from app.models import User
from app.modules.users import repo
from app.modules.users.schemas import MeOut, UpdateMeRequest


def is_active_user(db: Session, user_id: int) -> bool:
    return repo.get_active_user(db, user_id) is not None


def get_notification_phone(db: Session, user_id: int) -> str | None:
    """为短信通知读取启用账户的已绑定手机号。"""
    user = repo.get_active_user(db, user_id)
    if user is None or not user.phone_enc:
        return None
    try:
        return security.decrypt(user.phone_enc, "phone")
    except InvalidTag, ValueError:
        return None


def to_me_out(user: User) -> MeOut:
    masked = security.mask_phone(security.decrypt(user.phone_enc, "phone")) if user.phone_enc else None
    return MeOut(
        id=user.id,
        nickname=user.nickname,
        avatar_url=user.avatar_url,
        phone_masked=masked,
        has_phone=user.phone_enc is not None,
        created_at=user.created_at,
    )


def update_me(db: Session, user: User, body: UpdateMeRequest) -> MeOut:
    if body.nickname is not None:
        user.nickname = body.nickname
    if body.avatar_url is not None:
        user.avatar_url = body.avatar_url
    db.commit()
    return to_me_out(user)


def bind_phone(db: Session, user: User, code: str) -> MeOut:
    phone = get_wechat().get_phone_number(code)
    phone_hash = security.keyed_hash(phone, "phone")
    owner = repo.get_user_by_phone_hash(db, phone_hash)
    if owner is not None and owner.id != user.id:
        raise AppError(ErrorCode.PHONE_ALREADY_BOUND)
    user.phone_enc = security.encrypt(phone, "phone")
    user.phone_hash = phone_hash
    try:
        db.commit()
    except IntegrityError as e:
        # 并发绑定同一个号码，被唯一约束挡住
        db.rollback()
        raise AppError(ErrorCode.PHONE_ALREADY_BOUND) from e
    return to_me_out(user)


def cancel_account(db: Session, user: User, confirm: bool) -> None:
    if confirm is not True:
        raise AppError(ErrorCode.VALIDATION_ERROR, "请确认注销账号")
    # 函数内导入，避免模块间循环导入
    from app.modules.auth import service as auth_service
    from app.modules.photos import service as photo_service

    photo_service.purge_all_for_user(db, user.id)
    auth_service.revoke_all_for_user(db, user.id)
    user.status = "cancelled"
    user.nickname = None
    user.avatar_url = None
    user.phone_enc = None
    user.phone_hash = None
    db.commit()
