"""定时运行后台任务，部署入口为 python -m app.workers.runner。"""

import logging
import signal
from datetime import timedelta
from threading import Event
from time import monotonic

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.utils import utcnow
from app.modules.entitlements import service as entitlements
from app.modules.notify import service as notify
from app.modules.orders import service as orders
from app.modules.photos import service as photos
from app.modules.receipts import poller as receipts

log = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 60
ADVISORY_LOCK_KEY = 0x494450484F4E45  # IDPHONE
ORPHAN_UPLOAD_HOURS = 24


def purge_orphan_uploads(db: Session) -> int:
    """清理上传超过 24 小时仍未创建照片的原图。"""
    count = photos.purge_orphan_uploads(db, utcnow() - timedelta(hours=ORPHAN_UPLOAD_HOURS))
    db.commit()
    return count


def run_once(db: Session) -> None:
    """按顺序运行一轮定时任务；单项失败回滚后继续。"""
    for task in (
        receipts.poll_due,
        notify.send_due,
        orders.close_expired,
        entitlements.create_expiration_reminders,
        purge_orphan_uploads,
    ):
        try:
            task(db)
        except Exception as exc:
            log.error("定时任务失败 task=%s err=%s", task.__name__, type(exc).__name__)
            try:
                db.rollback()
            except SQLAlchemyError as rollback_exc:
                log.error("定时任务回滚失败 task=%s err=%s", task.__name__, type(rollback_exc).__name__)
                db.invalidate()


def _run_as_leader(stop: Event, interval: float) -> None:
    # 会话级锁由专用连接持有，任务会话的提交和回滚不影响锁。
    params = {"key": ADVISORY_LOCK_KEY}
    with engine.connect() as lock_connection:
        if not lock_connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), params):
            return
        try:
            lock_connection.commit()
            log.info("定时任务 worker 已获取锁")
            while not stop.is_set():
                started = monotonic()
                # 探测持锁连接是否断开。断开时退出本次运行，由 main 重新争锁。
                lock_connection.exec_driver_sql("SELECT 1")
                lock_connection.commit()
                with SessionLocal() as db:
                    run_once(db)
                stop.wait(max(0, interval - (monotonic() - started)))
        finally:
            if not lock_connection.invalidated:
                try:
                    lock_connection.execute(text("SELECT pg_advisory_unlock(:key)"), params)
                except SQLAlchemyError:
                    lock_connection.invalidate()
                    raise


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = Event()

    def request_stop(_signum, _frame) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    interval = getattr(settings, "worker_interval_seconds", DEFAULT_INTERVAL_SECONDS)
    while not stop.is_set():
        try:
            _run_as_leader(stop, interval)
        except SQLAlchemyError as exc:
            log.error("定时任务持锁连接异常 err=%s", type(exc).__name__)
        stop.wait(interval)
    log.info("定时任务 worker 已退出")


if __name__ == "__main__":
    main()
