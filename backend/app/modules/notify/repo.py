"""通知查询。"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import NotifyTask, UserIdentity

MINI_PROVIDER = "wx_mini"


def get_mini_identity(db: Session, user_id: int, *, for_update: bool = False) -> UserIdentity | None:
    stmt = (
        select(UserIdentity)
        .where(UserIdentity.user_id == user_id, UserIdentity.provider == MINI_PROVIDER)
        .order_by(UserIdentity.id)
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def find_step1_task(
    db: Session, *, application_id: int | None, entitlement_id: int | None, event: str
) -> NotifyTask | None:
    stmt = select(NotifyTask).where(
        NotifyTask.event == event, NotifyTask.step == 1, NotifyTask.channel == "mini_subscribe"
    )
    stmt = stmt.where(
        NotifyTask.application_id.is_(None)
        if application_id is None
        else NotifyTask.application_id == application_id
    )
    stmt = stmt.where(
        NotifyTask.entitlement_id.is_(None)
        if entitlement_id is None
        else NotifyTask.entitlement_id == entitlement_id
    )
    return db.scalar(stmt)


def insert_task_once(
    db: Session,
    *,
    user_id: int,
    event: str,
    step: int,
    application_id: int | None,
    entitlement_id: int | None,
    scheduled_at: datetime,
) -> bool:
    stmt = (
        insert(NotifyTask)
        .values(
            user_id=user_id,
            application_id=application_id,
            entitlement_id=entitlement_id,
            event=event,
            step=step,
            channel="mini_subscribe",
            scheduled_at=scheduled_at,
            status="pending",
        )
        .on_conflict_do_nothing(
            index_elements=[
                NotifyTask.application_id,
                NotifyTask.entitlement_id,
                NotifyTask.event,
                NotifyTask.step,
                NotifyTask.channel,
            ]
        )
        .returning(NotifyTask.id)
    )
    return db.scalar(stmt) is not None


def due_tasks(db: Session, now: datetime, limit: int) -> list[NotifyTask]:
    return list(
        db.scalars(
            select(NotifyTask)
            .where(NotifyTask.status == "pending", NotifyTask.scheduled_at <= now)
            .order_by(NotifyTask.scheduled_at, NotifyTask.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
