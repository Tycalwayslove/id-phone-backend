"""订单、权益测试共用的小工具。"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.utils import new_no, utcnow
from app.models import Entitlement, File, Order, OrderItem, Photo, Plan, UserIdentity
from app.modules.entitlements import service as entitlement_service
from app.modules.orders import service as order_service


def latest_user_id(db: Session) -> int:
    """刚登录的那个用户的 ID（测试库里只有本测试事务内创建的身份）。"""
    return db.scalar(select(UserIdentity.user_id).order_by(UserIdentity.id.desc()).limit(1))


def make_photo(db: Session, user_id: int) -> Photo:
    f = File(
        user_id=user_id,
        kind="original",
        bucket="test",
        storage_key=f"test/{uuid.uuid4().hex}.jpg",
        mime="image/jpeg",
        size_bytes=1,
    )
    db.add(f)
    db.flush()
    p = Photo(user_id=user_id, source="upload", original_file_id=f.id, status="active")
    db.add(p)
    db.flush()
    return p


def grant_plan(
    db: Session,
    user_id: int,
    plan: Plan,
    *,
    photo_id: int | None = None,
    paid_at: datetime | None = None,
    parent_entitlement_id: int | None = None,
) -> Entitlement:
    """绕过支付，直接按套餐发放一份权益（含订单和订单项）。"""
    paid_at = paid_at or utcnow()
    benefits = order_service.get_plan_benefits(db, plan.id)
    order = Order(
        order_no=new_no("O"),
        user_id=user_id,
        total_fen=plan.price_fen,
        paid_fen=plan.price_fen,
        status="paid",
        client="wx_mini",
        paid_at=paid_at,
        expire_at=paid_at,
    )
    db.add(order)
    db.flush()
    item = OrderItem(
        order_id=order.id,
        item_type="addon" if benefits.get("attach_to_parent") else "plan",
        plan_id=plan.id,
        photo_id=photo_id,
        unit_price_fen=plan.price_fen,
        amount_fen=plan.price_fen,
        snapshot={
            "plan_code": plan.code,
            "plan_name": plan.name,
            "benefits": benefits,
            "parent_entitlement_id": parent_entitlement_id,
        },
    )
    db.add(item)
    db.flush()
    return entitlement_service.grant_for_order_item(
        db, user_id=user_id, item=item, plan=plan, paid_at=paid_at
    )
