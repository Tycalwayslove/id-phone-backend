"""通知任务、订阅额度和收件地址查询。"""

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.integrations.notify_channels import CHANNEL_ORDER, MINI_SUBSCRIBE
from app.models import NotifyTask, UserIdentity, WecomContact


def get_mini_identity(db: Session, user_id: int, *, app_id: str) -> UserIdentity | None:
    return db.scalar(
        select(UserIdentity)
        .filter_by(user_id=user_id, provider="wx_mini", app_id=app_id)
        .order_by(UserIdentity.id)
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def get_mp_open_id(db: Session, user_id: int, *, app_id: str) -> str | None:
    stmt = select(UserIdentity.open_id).filter_by(user_id=user_id, provider="wx_mp")
    if app_id:
        stmt = stmt.filter_by(app_id=app_id)
    return db.scalar(stmt.order_by(UserIdentity.id).limit(1))


def get_wecom_recipient(db: Session, user_id: int) -> str | None:
    return db.scalar(
        select(WecomContact.external_userid)
        .where(WecomContact.user_id == user_id, WecomContact.removed_at.is_(None))
        .order_by(WecomContact.id)
        .limit(1)
    )


def find_step1_task(
    db: Session, *, application_id: int | None, entitlement_id: int | None, event: str
) -> NotifyTask | None:
    return db.scalar(
        select(NotifyTask)
        .filter_by(
            application_id=application_id,
            entitlement_id=entitlement_id,
            event=event,
            step=1,
            channel=MINI_SUBSCRIBE,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def insert_task_once(
    db: Session,
    *,
    user_id: int,
    event: str,
    step: int,
    application_id: int | None,
    entitlement_id: int | None,
    scheduled_at: datetime,
    channel: str = MINI_SUBSCRIBE,
    generation: int = 0,
) -> bool:
    stmt = (
        insert(NotifyTask)
        .values(
            user_id=user_id,
            application_id=application_id,
            entitlement_id=entitlement_id,
            event=event,
            step=step,
            channel=channel,
            scheduled_at=scheduled_at,
            status="pending",
            result={"generation": generation} if generation else None,
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


def cancel_pending_fallbacks(db: Session, task: NotifyTask) -> None:
    # 与升级锁定渠道的顺序一致，也能看到前一渠道刚提交的新任务。
    for channel in CHANNEL_ORDER[1:]:
        db.execute(
            update(NotifyTask)
            .filter_by(
                application_id=task.application_id,
                entitlement_id=task.entitlement_id,
                event=task.event,
                step=task.step,
                channel=channel,
                status="pending",
            )
            .values(status="cancelled")
        )


def reactivate_previous_fallback(
    db: Session, task: NotifyTask, channel: str, generation: int, scheduled_at: datetime
) -> None:
    db.execute(
        update(NotifyTask)
        .filter_by(
            application_id=task.application_id,
            entitlement_id=task.entitlement_id,
            event=task.event,
            step=task.step,
            channel=channel,
        )
        .where(func.coalesce(NotifyTask.result["generation"].as_integer(), 0) < generation)
        .values(status="pending", scheduled_at=scheduled_at, sent_at=None, result={"generation": generation})
    )


def next_due_task(db: Session, now: datetime, excluded_ids: set[int]) -> NotifyTask | None:
    stmt = (
        select(NotifyTask)
        .where(
            NotifyTask.status == "pending",
            NotifyTask.scheduled_at <= now,
            NotifyTask.channel.in_(CHANNEL_ORDER),
        )
        .order_by(NotifyTask.scheduled_at, NotifyTask.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if excluded_ids:
        stmt = stmt.where(NotifyTask.id.not_in(excluded_ids))
    return db.scalar(stmt)
