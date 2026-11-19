from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User


def get_user_by_phone_hash(db: Session, phone_hash: str) -> User | None:
    return db.scalar(select(User).where(User.phone_hash == phone_hash))
