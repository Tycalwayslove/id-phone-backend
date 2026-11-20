"""通知业务：创建通知任务、记录订阅授权、发送到期任务。"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.utils import utcnow
from app.integrations.notify_channels import (
    CHANNEL_ORDER,
    MINI_SUBSCRIBE,
    MP_TEMPLATE,
    SMS,
    WECOM,
    Notification,
    get_channel,
    get_template,
)
from app.integrations.wechat import DeliveryError
from app.models import NotifyTask
from app.modules.notify import repo
from app.modules.notify.schemas import SubscriptionQuota, TemplateOut
from app.modules.users import service as users_service

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RETRY_DELAY = timedelta(minutes=1)

_TEMPLATES = (
    TemplateOut(
        event="receipt_completed",
        template_id="TMPL_RECEIPT_COMPLETED_PLACEHOLDER",
        title="回执办理成功提醒",
    ),
    TemplateOut(
        event="receipt_rejected",
        template_id="TMPL_RECEIPT_REJECTED_PLACEHOLDER",
        title="回执被驳回提醒",
    ),
)
_FAKE_TEMPLATE_IDS = {template.event: template.template_id for template in _TEMPLATES}


def _channel_mode(channel: str) -> str:
    return {
        MINI_SUBSCRIBE: settings.mini_subscribe_mode,
        MP_TEMPLATE: settings.mp_template_mode,
        WECOM: settings.wecom_mode,
        SMS: settings.sms_mode,
    }[channel]


def _enabled_channels() -> set[str]:
    return {part.strip() for part in settings.notify_channels.split(",")}


def _mini_template_id(event: str, mode: str) -> str | None:
    template_id = get_template(MINI_SUBSCRIBE, event).get("template_id")
    return template_id or (_FAKE_TEMPLATE_IDS.get(event) if mode == "fake" else None)


def list_templates() -> list[TemplateOut]:
    if MINI_SUBSCRIBE not in _enabled_channels():
        return []
    mode = _channel_mode(MINI_SUBSCRIBE)
    templates = []
    for template in _TEMPLATES:
        template_id = _mini_template_id(template.event, mode)
        if template_id:
            templates.append(TemplateOut(event=template.event, title=template.title, template_id=template_id))
    return templates


def report_subscriptions(db: Session, *, user_id: int, accepted: list[str]) -> SubscriptionQuota:
    """用户点了“允许”的模板各加 1 次授权。没有小程序身份时返回空。"""
    identity = repo.get_mini_identity(db, user_id, app_id=settings.wx_mini_app_id)
    if identity is None:
        return SubscriptionQuota(quota={})
    known_ids = {template.template_id for template in list_templates()}
    # 整体替换字典再赋值，SQLAlchemy 才能检测到 JSONB 的变化。
    quota = dict(identity.subscribe_quota or {})
    for tid in set(accepted) & known_ids:
        quota[tid] = int(quota.get(tid, 0)) + 1
    identity.subscribe_quota = quota
    db.commit()
    return SubscriptionQuota(quota=quota)


def create_task(
    db: Session,
    *,
    user_id: int,
    event: str,
    application_id: int | None = None,
    entitlement_id: int | None = None,
) -> NotifyTask:
    """创建（或重新激活）一条小程序订阅消息任务。不 commit。"""
    if (application_id is None) == (entitlement_id is None):
        raise ValueError("application_id 和 entitlement_id 必须且只能传一个")
    now = utcnow()
    target = dict(application_id=application_id, entitlement_id=entitlement_id, event=event)
    task = repo.find_step1_task(db, **target)
    if task is None:
        repo.insert_task_once(db, **target, user_id=user_id, step=1, scheduled_at=now)
        task = repo.find_step1_task(db, **target)
        assert task is not None
    if task.status != "pending":
        # 再次驳回开启新一轮通知。上一轮尚未发出的降级任务随之取消。
        repo.cancel_pending_fallbacks(db, task)
        generation = (task.result or {}).get("generation", 0) + 1
        task.status = "pending"
        task.scheduled_at = now
        task.sent_at = None
        task.result = {"generation": generation}
        db.flush()
    return task


def create_task_once(
    db: Session,
    *,
    user_id: int,
    event: str,
    step: int,
    application_id: int | None = None,
    entitlement_id: int | None = None,
) -> bool:
    """仅首次创建该档的小程序订阅消息任务，返回是否新建。由调用方提交。"""
    if (application_id is None) == (entitlement_id is None):
        raise ValueError("application_id 和 entitlement_id 必须且只能传一个")
    return repo.insert_task_once(
        db,
        user_id=user_id,
        event=event,
        step=step,
        application_id=application_id,
        entitlement_id=entitlement_id,
        scheduled_at=utcnow(),
    )


def _enqueue_next_channel(
    db: Session, task: NotifyTask, enabled: set[str], generation: int, scheduled_at: datetime
) -> None:
    following = CHANNEL_ORDER[CHANNEL_ORDER.index(task.channel) + 1 :]
    for channel in following:
        if channel not in enabled:
            continue
        inserted = repo.insert_task_once(
            db,
            user_id=task.user_id,
            event=task.event,
            step=task.step,
            application_id=task.application_id,
            entitlement_id=task.entitlement_id,
            scheduled_at=scheduled_at,
            channel=channel,
            generation=generation,
        )
        if not inserted and generation:
            repo.reactivate_previous_fallback(db, task, channel, generation, scheduled_at)
        return


def _deliver(db: Session, task: NotifyTask, mode: str, delivery_id: str) -> None:
    channel = task.channel
    if channel == MINI_SUBSCRIBE:
        identity = repo.get_mini_identity(db, task.user_id, app_id=settings.wx_mini_app_id)
        template_id = _mini_template_id(task.event, mode)
        if identity is None or not template_id:
            raise DeliveryError("no_subscribe_quota", "skipped")
        quota = dict(identity.subscribe_quota or {})
        left = int(quota.get(template_id, 0))
        if left <= 0 or not identity.open_id:
            raise DeliveryError("no_subscribe_quota", "skipped")
        try:
            get_channel(channel, mode).send(
                Notification(identity.open_id, task.event, task.step, delivery_id)
            )
        except DeliveryError as exc:
            if exc.reason == "subscription_unavailable":
                quota[template_id] = 0
                identity.subscribe_quota = quota
            raise
        quota[template_id] = left - 1
        identity.subscribe_quota = quota
        return

    if channel == MP_TEMPLATE:
        recipient = repo.get_mp_open_id(db, task.user_id, app_id=settings.wx_mp_app_id)
        if not recipient:
            raise DeliveryError("no_mp_identity", "skipped")
    elif channel == WECOM:
        recipient = ""
        if mode == "fake":
            recipient = repo.get_wecom_recipient(db, task.user_id)
            if not recipient:
                raise DeliveryError("no_wecom_contact", "skipped")
    else:
        recipient = users_service.get_notification_phone(db, task.user_id)
        if not recipient:
            raise DeliveryError("no_phone", "skipped")
    get_channel(channel, mode).send(Notification(recipient, task.event, task.step, delivery_id))


def _process_task(db: Session, task: NotifyTask, enabled: set[str], cutoff: datetime) -> None:
    mode = _channel_mode(task.channel)
    previous = task.result or {}
    generation = previous.get("generation", 0)
    result: dict[str, str | int] = {"mode": mode}
    if generation:
        result["generation"] = generation
    if not users_service.is_active_user(db, task.user_id):
        task.status = "cancelled"
        task.result = {**result, "reason": "inactive_user"}
        return
    delivery_id = f"{task.id:016x}{generation:016x}"
    try:
        if task.channel not in enabled:
            raise DeliveryError("channel_disabled", "skipped")
        _deliver(db, task, mode, delivery_id)
    except DeliveryError as exc:
        task.result = {**result, "reason": exc.reason}
        attempts = previous.get("attempts", 0)
        if exc.outcome == "retry":
            attempts += 1
        if attempts:
            task.result["attempts"] = attempts
        if exc.outcome == "retry" and attempts < MAX_ATTEMPTS:
            task.scheduled_at = utcnow() + RETRY_DELAY * 2 ** (attempts - 1)
            return
        task.status = "skipped" if exc.outcome == "skipped" else "failed"
        _enqueue_next_channel(db, task, enabled, generation, cutoff)
    else:
        task.status = "sent"
        task.sent_at = utcnow()
        if "attempts" in previous:
            result["attempts"] = previous["attempts"] + 1
        task.result = result


def send_due(db: Session, limit: int = 100) -> int:
    """逐条锁定并提交到期任务，返回本轮提交的任务数。"""
    cutoff = utcnow()
    enabled = _enabled_channels()
    processed = 0
    rolled_back_ids: set[int] = set()
    for _ in range(limit):
        task = repo.next_due_task(db, cutoff, rolled_back_ids)
        if task is None:
            db.commit()
            break
        task_id, channel = task.id, task.channel
        try:
            _process_task(db, task, enabled, cutoff)
            db.commit()
        except Exception as exc:
            db.rollback()
            rolled_back_ids.add(task_id)
            log.error("通知任务回滚 id=%s channel=%s err=%s", task_id, channel, type(exc).__name__)
        else:
            processed += 1
    return processed
