from datetime import timedelta

from sqlalchemy import select

from app.core.utils import utcnow
from app.models import ClientApp, User, UserIdentity
from scripts.backfill_user_source_app import SourceAssignment, apply_backfill, plan_backfill


def test_backfill_uses_earliest_identity_and_is_idempotent(db):
    app = ClientApp(platform="web", app_id="web-client", name="已命名网页", status="disabled")
    db.add(app)
    db.flush()
    legacy, recorded, no_identity = User(), User(source_app_id=app.id), User()
    db.add_all([legacy, recorded, no_identity])
    db.flush()
    now = utcnow()
    rows = [
        (legacy, "wx_mini", "wx-recent", now),
        (legacy, "h5", "web-client", now - timedelta(days=1)),
        (legacy, "wx_mini", "wx-tied", now - timedelta(days=1)),
        (recorded, "wx_mini", "wx-recorded", now),
    ]
    for user, provider, app_id, created_at in rows:
        db.add(
            UserIdentity(
                user_id=user.id, provider=provider, app_id=app_id, open_id="fake-id", created_at=created_at
            )
        )
        db.flush()

    plan = plan_backfill(db)
    assert plan == [SourceAssignment(legacy.id, "web", "web-client")]
    assert legacy.source_app_id is None and no_identity.source_app_id is None
    assert list(db.scalars(select(ClientApp))) == [app]
    assert apply_backfill(db, plan) == 1
    assert apply_backfill(db, plan) == 0
    db.expire_all()  # 回填用批量 UPDATE，重新从数据库读取
    assert legacy.source_app_id == recorded.source_app_id == app.id
    assert no_identity.source_app_id is None
    assert plan_backfill(db) == []
    assert app.status == "disabled" and app.name == "已命名网页"
