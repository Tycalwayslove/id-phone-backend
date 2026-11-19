"""通知业务：创建通知任务、记录订阅授权、发送到期任务。"""

from sqlalchemy.orm import Session

from app.core.utils import utcnow
from app.models import NotifyTask
from app.modules.notify import repo
from app.modules.notify.schemas import SubscriptionQuota, TemplateOut

# 订阅消息模板 ID：这里是占位值。上线前必须换成小程序后台（订阅消息）申请到的真实模板 ID。
TEMPLATES: list[TemplateOut] = [
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
]
_TEMPLATE_BY_EVENT = {t.event: t.template_id for t in TEMPLATES}
_KNOWN_IDS = {t.template_id for t in TEMPLATES}


def list_templates() -> list[TemplateOut]:
    return TEMPLATES


def report_subscriptions(db: Session, *, user_id: int, accepted: list[str]) -> SubscriptionQuota:
    """用户点了“允许”的模板各加 1 次授权。没有小程序身份时返回空。"""
    identity = repo.get_mini_identity(db, user_id, for_update=True)
    if identity is None:
        return SubscriptionQuota(quota={})
    # 整体替换字典再赋值，SQLAlchemy 才能检测到 JSONB 的变化
    quota = dict(identity.subscribe_quota or {})
    for tid in set(accepted) & _KNOWN_IDS:
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
    task = repo.find_step1_task(db, application_id=application_id, entitlement_id=entitlement_id, event=event)
    if task is not None:
        # 已发送、被跳过或失败的任务：再次出现同一事件（如再次驳回）需要重新通知
        if task.status in ("sent", "skipped", "failed", "cancelled"):
            task.status = "pending"
            task.scheduled_at = now
            task.sent_at = None
            task.result = None
            db.flush()
        return task
    task = NotifyTask(
        user_id=user_id,
        application_id=application_id,
        entitlement_id=entitlement_id,
        event=event,
        step=1,
        channel="mini_subscribe",
        scheduled_at=now,
        status="pending",
    )
    db.add(task)
    db.flush()
    return task


def send_due(db: Session, limit: int = 100) -> int:
    """发送到期任务，返回处理数量。目前只有 fake 发送：记录结果，不真正调用微信。"""
    now = utcnow()
    tasks = repo.due_tasks(db, now, limit)
    for task in tasks:
        template_id = _TEMPLATE_BY_EVENT.get(task.event)
        identity = repo.get_mini_identity(db, task.user_id, for_update=True)
        left = int((identity.subscribe_quota or {}).get(template_id, 0)) if identity and template_id else 0
        if left <= 0:
            # TODO: 没有订阅授权时升级到公众号模板消息 -> 企业微信 -> 短信（新增 step 2、3…）
            task.status = "skipped"
            task.result = {"mode": "fake", "reason": "no_subscribe_quota"}
            continue
        quota = dict(identity.subscribe_quota)
        quota[template_id] = left - 1  # 一次授权只能发一条
        identity.subscribe_quota = quota
        task.status = "sent"
        task.sent_at = now
        task.result = {"mode": "fake"}
    db.commit()
    return len(tasks)
