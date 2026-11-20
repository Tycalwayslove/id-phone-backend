"""规格查询。规格是公开数据，不区分用户。"""

from sqlalchemy import exists, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.utils import contains_pattern
from app.models import Provider, ProviderSpec, RouteRule, Spec


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
        q = q.where(Spec.name.ilike(contains_pattern(keyword), escape="\\"))
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


def lock_catalog_provider(db: Session, code: str) -> Provider | None:
    stmt = select(Provider).where(Provider.code == code).with_for_update(key_share=True)
    return db.scalar(stmt.execution_options(populate_existing=True))


def lock_provider_specs(db: Session, provider_id: int) -> list[ProviderSpec]:
    stmt = (
        select(ProviderSpec)
        .where(ProviderSpec.provider_id == provider_id)
        .order_by(ProviderSpec.id)
        .with_for_update()
    )
    return list(db.scalars(stmt.execution_options(populate_existing=True)))


def lock_specs(db: Session, spec_ids: set[int]) -> dict[int, Spec]:
    if not spec_ids:
        return {}
    # 不同服务商可映射同一个规格。统一锁定次序，允许其他事务写入外键引用。
    stmt = select(Spec).where(Spec.id.in_(spec_ids)).order_by(Spec.id).with_for_update(key_share=True)
    return {spec.id: spec for spec in db.scalars(stmt.execution_options(populate_existing=True))}


def insert_catalog_spec(db: Session, values: dict) -> Spec | None:
    stmt = insert(Spec).values(**values).on_conflict_do_nothing(index_elements=[Spec.code]).returning(Spec)
    return db.scalar(stmt)
