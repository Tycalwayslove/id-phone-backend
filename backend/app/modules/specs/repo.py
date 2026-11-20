"""规格查询。规格是公开数据，不区分用户。"""

from sqlalchemy import exists, func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.utils import contains_pattern
from app.models import Provider, ProviderSpec, RouteRule, Spec


def list_active(
    db: Session,
    *,
    category: str | None,
    keyword: str | None,
    region_codes: set[str],
    after: tuple[int, int] | None,
    limit: int,
) -> list[Spec]:
    """按 (sort, id) 升序取启用的规格；after 是上一页最后一条的 (sort, id)。"""
    q = select(Spec).where(Spec.status == "active")
    if category:
        q = q.where(Spec.category == category)
    if keyword:
        q = q.where(Spec.name.ilike(contains_pattern(keyword), escape="\\"))
    if region_codes:
        q = q.where(or_(Spec.region_code.is_(None), Spec.region_code.in_(region_codes | {""})))
    if after is not None:
        q = q.where(tuple_(Spec.sort, Spec.id) > tuple_(after[0], after[1]))
    return list(db.scalars(q.order_by(Spec.sort, Spec.id).limit(limit)))


def active_region_counts(db: Session) -> list[tuple[str, int]]:
    stmt = (
        select(Spec.region_code, func.count())
        .where(Spec.status == "active", Spec.region_code.is_not(None))
        .group_by(Spec.region_code)
        .order_by(Spec.region_code)
    )
    return [(code, count) for code, count in db.execute(stmt) if code is not None]


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


def lock_catalog_merge(db: Session) -> None:
    # 不同服务商同时同步时，后一笔事务需要看到前一笔新建的规格和映射。
    db.execute(select(func.pg_advisory_xact_lock(func.hashtext("id-phone:spec-catalog"))))


def catalog_specs(db: Session) -> list[Spec]:
    return list(db.scalars(select(Spec).order_by(Spec.id)))


def upstream_siblings(db: Session, provider: Provider) -> list[Provider]:
    """同一上游分组里的其他服务商（编号体系相同）。"""
    if not provider.upstream_group:
        return []
    stmt = (
        select(Provider)
        .where(Provider.upstream_group == provider.upstream_group, Provider.id != provider.id)
        .order_by(Provider.id)
    )
    return list(db.scalars(stmt))


def upstream_mappings(db: Session, provider: Provider) -> list[ProviderSpec]:
    stmt = (
        select(ProviderSpec)
        .join(Provider, ProviderSpec.provider_id == Provider.id)
        .where(Provider.upstream_group == provider.upstream_group, Provider.id != provider.id)
        .order_by(ProviderSpec.spec_id, ProviderSpec.id)
    )
    return list(db.scalars(stmt))


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


def add_catalog_route(db: Session, *, spec_id: int, provider_id: int, is_enabled: bool) -> None:
    stmt = insert(RouteRule).values(spec_id=spec_id, provider_id=provider_id, is_enabled=is_enabled)
    db.execute(
        stmt.on_conflict_do_nothing(
            index_elements=[RouteRule.spec_id, RouteRule.region_code, RouteRule.provider_id]
        )
    )
