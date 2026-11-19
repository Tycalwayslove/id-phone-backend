"""补偿轮询：回调丢了或提交超时的情况下，主动向服务商查询结果。

由定时任务调用 poll_due（暂未接入调度）。
"""

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.utils import utcnow
from app.integrations.receipt_providers import get_provider
from app.models import Provider
from app.modules.receipts import repo
from app.modules.receipts.service import apply_provider_status

log = logging.getLogger("app.receipts.poller")

_RETRY_DELAY = timedelta(minutes=5)


def poll_due(db: Session, limit: int = 50) -> int:
    """查询到期的当前提交，应用结果。每条单独提交，返回处理条数。"""
    ids = repo.due_attempt_ids(db, utcnow(), limit)
    done = 0
    for attempt_id in ids:
        attempt = repo.get_attempt(db, attempt_id, for_update=True)  # 被别的进程锁住就跳过
        if attempt is None or attempt.status not in repo.POLLABLE_STATUSES:
            db.rollback()
            continue
        try:
            if not attempt.provider_order_no:
                # 超时未拿到服务商单号，无法按单号查询；稍后再看，交给人工或后续的幂等查询处理
                attempt.next_poll_at = utcnow() + _RETRY_DELAY
            else:
                provider = db.get(Provider, attempt.provider_id)
                status = get_provider(provider.adapter, provider.code).query(attempt.provider_order_no)
                apply_provider_status(db, attempt, status)
            db.commit()
            done += 1
        except Exception as e:
            db.rollback()
            log.warning("轮询失败 attempt=%s err=%s", attempt_id, type(e).__name__)
            retry = repo.get_attempt(db, attempt_id)
            if retry is not None:
                retry.next_poll_at = utcnow() + _RETRY_DELAY
                db.commit()
    return done
