"""规格查询。规格是公开数据，不区分用户。"""

from sqlalchemy import exists, select, tuple_
from sqlalchemy.orm import Session

from app.models import Provider, ProviderSpec, RouteRule, Spec


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_active(
    db: Session,
    *,
    category: str | None,
    keyword: str | None,
    after: tuple[int, int] | None,
    limit: int,
) -> list[Spec]:
    """按 (sort, id) 升序取启用的规格；after 是上一页最后一条的 (sort, id)。"""
    q = select(Spec).where(Spec.status == "active")
    if category:
        q = q.where(Spec.category == category)
    if keyword:
        q = q.where(Spec.name.ilike(f"%{_escape_like(keyword)}%", escape="\\"))
    if after is not None:
        q = q.where(tuple_(Spec.sort, Spec.id) > tuple_(after[0], after[1]))
    return list(db.scalars(q.order_by(Spec.sort, Spec.id).limit(limit)))


def get_active_by_code(db: Session, code: str) -> Spec | None:
    return db.scalar(select(Spec).where(Spec.code == code, Spec.status == "active"))


def supports_receipt(db: Session, spec_id: int) -> bool:
    """有启用的路由规则 + 启用的服务商规格 + 未停用的服务商，才算能办回执。"""
    q = select(
        exists()
        .where(
            RouteRule.spec_id == spec_id,
            RouteRule.is_enabled.is_(True),
            ProviderSpec.spec_id == RouteRule.spec_id,
            ProviderSpec.provider_id == RouteRule.provider_id,
            ProviderSpec.is_enabled.is_(True),
            Provider.id == RouteRule.provider_id,
            Provider.status != "disabled",
        )
        .correlate()
    )
    return bool(db.scalar(q))
