"""补偿轮询，处理服务商结果和未转存的回执图片。"""

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core import security
from app.core.config import settings
from app.core.utils import utcnow
from app.integrations.receipt_providers import get_provider
from app.models import Provider, ReceiptApplication, ReceiptAttempt
from app.modules.photos import service as photo_service
from app.modules.receipts import receipt_image, repo
from app.modules.receipts.service import apply_provider_status, manual_review_deadline

log = logging.getLogger("app.receipts.poller")

_RETRY_DELAY = timedelta(minutes=5)


def _store_receipt_image(db: Session, app: ReceiptApplication, attempt: ReceiptAttempt) -> None:
    event = repo.get_receipt_image_event(db, attempt)
    if event and (encrypted_url := event.payload.get(repo.RECEIPT_IMAGE_URL)):
        url = security.decrypt(bytes.fromhex(encrypted_url), "receipt_image_url")
        data, mime, ext = receipt_image.download(url)
        file = photo_service.save_file(
            db, user_id=app.user_id, kind="receipt", data=data, mime=mime, ext=ext, owner=f"a{app.id}"
        )
        app.receipt_file_id = file.id
        event.payload = {key: value for key, value in event.payload.items() if key != repo.RECEIPT_IMAGE_URL}
    attempt.next_poll_at = None


def _poll_status(db: Session, attempt: ReceiptAttempt) -> None:
    status = None
    real = settings.receipt_mode == "real"
    if attempt.provider_order_no:
        provider = db.get(Provider, attempt.provider_id)
        try:
            status = get_provider(provider.adapter, provider.code).query(attempt.provider_order_no)
        except TimeoutError:
            if not real:
                raise
    now = utcnow()
    if real and (status is None or status.result == "processing"):
        deadline = manual_review_deadline(attempt)
        if now >= deadline:
            attempt.status = "unknown"
            attempt.request_payload = {**(attempt.request_payload or {}), repo.MANUAL_REVIEW_REQUIRED: True}
            attempt.next_poll_at = None
            return
        if status is None:
            attempt.next_poll_at = min(now + _RETRY_DELAY, deadline)
        else:
            apply_provider_status(db, attempt, status)
            attempt.next_poll_at = min(attempt.next_poll_at, deadline)
    elif status is None:
        attempt.next_poll_at = now + _RETRY_DELAY
    else:
        apply_provider_status(db, attempt, status)


def poll_due(db: Session, limit: int = 50) -> int:
    """处理到期的当前提交。每条单独提交，返回处理条数。"""
    ids = repo.due_attempt_ids(db, utcnow(), limit)
    done = 0
    for attempt_id in ids:
        locked = repo.lock_attempt(db, attempt_id, skip_locked=True)
        if locked is None:
            db.rollback()
            continue
        app, attempt = locked
        can_poll = attempt.status in repo.POLLABLE_STATUSES and app.status in ("pending", "processing")
        needs_image = attempt.status == app.status == "completed" and app.receipt_file_id is None
        if (
            not attempt.is_current
            or attempt.next_poll_at is None
            or attempt.next_poll_at > utcnow()
            or not (can_poll or needs_image)
        ):
            db.rollback()
            continue
        try:
            with db.begin_nested():
                if needs_image:
                    _store_receipt_image(db, app, attempt)
                else:
                    _poll_status(db, attempt)
            done += 1
        except Exception as exc:
            log.warning("回执轮询失败 attempt=%s err=%s", attempt_id, type(exc).__name__)
            attempt.next_poll_at = utcnow() + _RETRY_DELAY
        db.commit()
    return done
