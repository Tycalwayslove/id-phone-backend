"""规格查询与服务商目录同步。写入由调用方统一提交。"""

import logging
import re
from collections import defaultdict
from dataclasses import replace

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.pagination import PageParams
from app.core.regions import province_of, region_name, resolve_region
from app.core.utils import utcnow
from app.integrations.receipt_providers import open_catalog_provider
from app.integrations.receipt_providers.base import ProviderItem
from app.models import Provider, ProviderSpec, Spec
from app.modules.specs import repo
from app.modules.specs.schemas import (
    ProviderSyncChange,
    ProviderSyncItem,
    ProviderSyncResult,
    SpecDetail,
    SpecFields,
    SpecOut,
    SpecPage,
    SpecRegionCity,
    SpecRegionProvince,
)

log = logging.getLogger(__name__)
_NAME_NORMALIZATION = str.maketrans({" ": None, "　": None, "（": "(", "）": ")"})
_EXAM_WORDS = ("考试", "报名", "网申", "学籍", "中考", "高考", "人事")
_RECEIPT_FIELDS = {
    "text_name": ("name", "姓名"),
    "text_idcard": ("idcard", "身份证号"),
    "text_mobile": ("mobile", "手机号"),
    "text_city": ("city", "所在城市"),
}


def get_active_spec(db: Session, code: str) -> Spec:
    """跨模块函数：取启用的规格，不存在或已下架抛 SPEC_NOT_FOUND。"""
    spec = repo.get_active_by_code(db, code)
    if spec is None:
        raise AppError(ErrorCode.SPEC_NOT_FOUND)
    return spec


def _parse_cursor(page: PageParams) -> tuple[int, int] | None:
    data = page.cursor_values()
    if not data:
        return None
    s, i = data.get("s"), data.get("i")
    if isinstance(s, int) and isinstance(i, int):
        return s, i
    return None


def list_specs(
    db: Session,
    *,
    category: str | None,
    keyword: str | None,
    page: PageParams,
    region_code: str | None = None,
) -> SpecPage:
    region_codes = None
    if region_code == "national":
        region_codes = set()
    elif region_code:
        region_codes = {region_code, province_of(region_code) or region_code}
    rows = repo.list_active(
        db,
        category=category,
        keyword=keyword.strip() if keyword else None,
        region_codes=region_codes,
        after=_parse_cursor(page),
        limit=page.fetch_limit,
    )
    rows, next_cursor = page.slice(rows, cursor_of=lambda r: {"s": r.sort, "i": r.id})
    receipt_ids = repo.receipt_spec_ids(db, [spec.id for spec in rows])
    return SpecPage(
        items=[SpecOut(**_spec_fields(spec), supports_receipt=spec.id in receipt_ids) for spec in rows],
        next_cursor=next_cursor,
    )


def _spec_fields(spec: Spec) -> dict:
    return SpecFields.model_validate(spec).model_dump(exclude_computed_fields=True)


def list_spec_regions(db: Session) -> list[SpecRegionProvince]:
    counts = dict(repo.active_region_counts(db))
    cities: dict[str, list[SpecRegionCity]] = defaultdict(list)
    provinces = set()
    for code, count in counts.items():
        province = province_of(code)
        name = region_name(code)
        if province is None or name is None:
            continue
        provinces.add(province)
        if province != code:
            cities[province].append(SpecRegionCity(region_code=code, region_name=name, spec_count=count))
    return [
        SpecRegionProvince(
            region_code=code,
            region_name=region_name(code),
            spec_count=counts.get(code, 0) + sum(city.spec_count for city in cities[code]),
            province_spec_count=counts.get(code, 0),
            cities=cities[code],
        )
        for code in sorted(provinces)
    ]


def get_spec_detail(db: Session, code: str) -> SpecDetail:
    return _spec_detail(db, get_active_spec(db, code))


def get_preview_spec(db: Session) -> SpecDetail:
    configured_code = settings.preview_spec_code
    spec = repo.get_active_by_code(db, configured_code) if configured_code else None
    if spec is None:
        spec = repo.get_default_preview_spec(db)
    if spec is None:
        raise AppError(ErrorCode.SPEC_NOT_FOUND)
    return _spec_detail(db, spec)


def _spec_detail(db: Session, spec: Spec) -> SpecDetail:
    return SpecDetail(
        **_spec_fields(spec),
        dpi=spec.dpi,
        bg_colors=spec.bg_colors,
        file_size_min_kb=spec.file_size_min_kb,
        file_size_max_kb=spec.file_size_max_kb,
        beauty_max=spec.beauty_max,
        form_schema=spec.form_schema,
        supports_receipt=spec.id in repo.receipt_spec_ids(db, [spec.id]),
        official_valid_days=spec.official_valid_days,
    )


def _load_catalog(adapter: str, provider_code: str) -> dict[str, ProviderItem]:
    catalog: dict[str, ProviderItem] = {}
    try:
        with open_catalog_provider(adapter, provider_code) as provider:
            for item in provider.list_items():
                if item.provider_item_id in catalog:
                    raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "回执服务商目录含重复规格编号")
                catalog[item.provider_item_id] = item
    except TimeoutError:
        pass
    else:
        unknown = sum(item.unknown_color_count for item in catalog.values())
        if unknown:
            log.warning("回执服务商目录已跳过 %d 个未知底色", unknown)
        return catalog
    raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "读取回执服务商规格目录超时")


def _fill_receipt_metadata(db: Session, provider: Provider, catalog: dict[str, ProviderItem]) -> None:
    """有的服务商列表不带回执标记和办理字段（如黔微云）。同上游编号一致，从兄弟服务商的目录补齐，
    这样先同步哪家结果都一样。兄弟目录读不到就照常继续。"""
    missing = {item_id for item_id, item in catalog.items() if item.is_receipt is None}
    if not missing:
        return
    for sibling in repo.upstream_siblings(db, provider):
        try:
            sibling_catalog = _load_catalog(sibling.adapter, sibling.code)
        except AppError:
            log.warning("同上游服务商 %s 目录读取失败，%s 的回执标记无法补齐", sibling.code, provider.code)
            continue
        for item_id in list(missing):
            source = sibling_catalog.get(item_id)
            if source is None or source.is_receipt is None:
                continue
            item = catalog[item_id]
            catalog[item_id] = replace(
                item,
                is_receipt=source.is_receipt,
                receipt_fields=item.receipt_fields or source.receipt_fields,
                provider_category=item.provider_category or source.provider_category,
            )
            missing.discard(item_id)
        if not missing:
            return


def _photo_fields(item: ProviderItem) -> dict:
    return {
        "width_px": item.width_px,
        "height_px": item.height_px,
        "width_mm": item.width_mm,
        "height_mm": item.height_mm,
        "dpi": item.dpi,
        "bg_colors": item.bg_colors,
        "file_size_min_kb": item.file_size_min_kb,
        "file_size_max_kb": item.file_size_max_kb,
    }


def _spec_identity(spec: Spec | ProviderItem) -> tuple[str, int, int]:
    return (spec.name.translate(_NAME_NORMALIZATION), spec.width_px, spec.height_px)


def _receipt_form(fields: list[str]) -> tuple[list[dict], dict[str, str]]:
    schema = []
    mapping = {}
    known_keys = {_RECEIPT_FIELDS[field][0] for field in fields if field in _RECEIPT_FIELDS}
    for field in fields:
        if field not in _RECEIPT_FIELDS and field in known_keys:
            continue
        key, label = _RECEIPT_FIELDS.get(field, (field, field))
        schema.append({"key": key, "label": label, "required": True})
        mapping[key] = field
    return schema, mapping


def _create_catalog_spec(
    db: Session, prefix: str, item: ProviderItem, *, auto_publish: bool, form_schema: list[dict]
) -> Spec:
    base = re.sub(r"[^a-z0-9_]+", "_", f"cat_{prefix}_{item.provider_item_id}".lower())
    name = item.name.translate(_NAME_NORMALIZATION)
    category = (
        "receipt" if item.is_receipt else "exam" if any(word in name for word in _EXAM_WORDS) else "normal"
    )
    values = {
        **_photo_fields(item),
        "name": item.name,
        "category": category,
        "cert_type": "unknown",
        "region_code": resolve_region(name),
        "form_schema": form_schema if category == "receipt" else [],
        "status": "active" if auto_publish else "inactive",
        "sort": item.sort,
    }
    code = base[:64]
    index = 2
    # 运营已占用同名编码时，另建规格，避免把无关规格纳入同步。
    while (spec := repo.insert_catalog_spec(db, {**values, "code": code})) is None:
        suffix = f"_{index}"
        code = base[: 64 - len(suffix)] + suffix
        index += 1
    return spec


def _sync_detail(
    spec: Spec,
    item_id: str,
    change: ProviderSyncChange,
    changed_fields: list[str] | None = None,
    *,
    item: ProviderItem | None = None,
) -> ProviderSyncItem:
    return ProviderSyncItem(
        provider_item_id=item_id,
        spec_code=spec.code,
        spec_name=spec.name,
        change=change,
        changed_fields=changed_fields or [],
        unknown_receipt_fields=[field for field in item.receipt_fields if field not in _RECEIPT_FIELDS]
        if item
        else [],
    )


def sync_provider_specs(db: Session, provider_code: str, *, auto_publish: bool = True) -> ProviderSyncResult:
    """读取全量目录后同步规格，保留运营配置。只 flush，由调用方提交。"""
    provider = repo.lock_catalog_provider(db, provider_code)
    if provider is None:
        raise AppError(ErrorCode.NOT_FOUND, "服务商不存在")
    catalog = _load_catalog(provider.adapter, provider_code)
    _fill_receipt_metadata(db, provider, catalog)
    repo.lock_catalog_merge(db)
    mappings = repo.lock_provider_specs(db, provider.id)
    specs = repo.lock_specs(db, {row.spec_id for row in mappings})
    synced_at = utcnow()
    seen = set()
    items = []
    for row in mappings:
        item_id = row.provider_item_id
        spec = specs[row.spec_id]
        item = catalog.get(item_id)
        if item is None:
            if row.is_enabled:
                row.is_enabled = False
                items.append(_sync_detail(spec, item_id, "disabled"))
            continue
        fields = _photo_fields(item)
        changed = [key for key, value in fields.items() if getattr(spec, key) != value]
        for key in changed:
            setattr(spec, key, fields[key])
        seen.add(item_id)
        row.last_synced_at = synced_at
        items.append(_sync_detail(spec, item_id, "updated" if changed else "unchanged", changed, item=item))

    # 历史上同一服务商规格可关联多个本地规格，例如同一规格的不同地区。上面会逐条更新。
    linked_spec_ids = set(specs)
    upstream = defaultdict(list)
    if provider.upstream_group:
        for row in repo.upstream_mappings(db, provider):
            upstream[row.provider_item_id].append(row)
    by_name_size = defaultdict(list)
    by_id = {spec.id: spec for spec in repo.catalog_specs(db)}
    for spec in by_id.values():
        by_name_size[_spec_identity(spec)].append(spec)

    for item_id, item in sorted(catalog.items()):
        if item_id in seen:
            continue
        sibling = next((row for row in upstream[item_id] if row.spec_id not in linked_spec_ids), None)
        spec = (
            by_id[sibling.spec_id]
            if sibling
            else next(
                (
                    candidate
                    for candidate in by_name_size[_spec_identity(item)]
                    if candidate.id not in linked_spec_ids
                ),
                None,
            )
        )
        form_schema, param_mapping = _receipt_form(item.receipt_fields)
        if spec is None:
            spec = _create_catalog_spec(
                db,
                provider.upstream_group or provider_code,
                item,
                auto_publish=auto_publish,
                form_schema=form_schema,
            )
        if sibling and item.is_receipt is None and not param_mapping:
            # 同上游的列表可能省略回执参数，使用已匹配的同编号映射。
            param_mapping = dict(sibling.param_mapping)
        db.add(
            ProviderSpec(
                provider_id=provider.id,
                spec_id=spec.id,
                provider_item_id=item_id,
                is_enabled=auto_publish,
                cost_fen=0,
                param_mapping=param_mapping if spec.category == "receipt" else {},
                last_synced_at=synced_at,
            )
        )
        if auto_publish:
            repo.add_catalog_route(
                db,
                spec_id=spec.id,
                provider_id=provider.id,
                is_enabled=spec.category == "receipt" and item.is_receipt is not False,
            )
        linked_spec_ids.add(spec.id)
        items.append(_sync_detail(spec, item_id, "created", item=item))

    db.flush()
    return ProviderSyncResult(
        created=sum(item.change == "created" for item in items),
        updated=sum(item.change == "updated" for item in items),
        unchanged=sum(item.change == "unchanged" for item in items),
        disabled=sum(item.change == "disabled" for item in items),
        items=items,
    )
