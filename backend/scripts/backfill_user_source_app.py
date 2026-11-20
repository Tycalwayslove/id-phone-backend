"""为未记录来源的用户按最早的登录身份回填应用。默认只打印计划。"""

import argparse
from dataclasses import dataclass
from itertools import batched

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import User, UserIdentity
from app.modules.auth.repo import client_app_platform, ensure_client_app


@dataclass(frozen=True)
class SourceAssignment:
    user_id: int
    platform: str
    app_id: str


def plan_backfill(db: Session) -> list[SourceAssignment]:
    earliest_identity = (
        select(UserIdentity.id)
        .where(UserIdentity.user_id == User.id)
        .order_by(UserIdentity.created_at, UserIdentity.id)
        .limit(1)
        .correlate(User)
        .scalar_subquery()
    )
    rows = db.execute(
        select(User.id, UserIdentity.provider, UserIdentity.app_id)
        .join(UserIdentity, UserIdentity.id == earliest_identity)
        .where(User.source_app_id.is_(None))
        .order_by(User.id)
    )
    return [
        SourceAssignment(user_id, client_app_platform(provider), app_id) for user_id, provider, app_id in rows
    ]


def apply_backfill(db: Session, plan: list[SourceAssignment]) -> int:
    users_by_app: dict[tuple[str, str], list[int]] = {}
    for row in plan:
        users_by_app.setdefault((row.platform, row.app_id), []).append(row.user_id)
    count = 0
    for (platform, app_id), user_ids in sorted(users_by_app.items()):
        source_app_id = ensure_client_app(db, platform=platform, app_id=app_id)
        for batch in batched(user_ids, 1_000, strict=False):
            result = db.execute(
                update(User)
                .where(User.id.in_(batch), User.source_app_id.is_(None))
                .values(source_app_id=source_app_id)
            )
            count += result.rowcount
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="执行回填。默认仅打印计划。")
    args = parser.parse_args()
    with SessionLocal.begin() as db:
        plan = plan_backfill(db)
        for row in plan:
            print(f"用户 {row.user_id} ← {row.platform} / {row.app_id}")
        count = apply_backfill(db, plan) if args.apply else len(plan)
    print(f"{'已回填' if args.apply else '计划回填'} {count} 位用户。")


if __name__ == "__main__":
    main()
