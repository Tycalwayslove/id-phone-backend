"""规格查询与服务商目录同步。写入由调用方统一提交。"""

import re
from dataclasses import replace

from sqlalchemy.orm import Session

from app.core.deps import PageParams
from app.core.errors import AppError, ErrorCode
from app.core.utils import decode_cursor, encode_cursor, utcnow
from app.integrations.receipt_providers import open_catalog_provider
from app.integrations.receipt_providers.base import ProviderItem
from app.models import ProviderSpec, Spec
from app.modules.specs import repo
from app.modules.specs.schemas import (
    ProviderSyncChange,
    ProviderSyncItem,
    ProviderSyncResult,
    SpecDetail,
    SpecOut,
    SpecPage,
)


def get_active_spec(db: Session, code: str) -> Spec:
    """跨模块函数：取启用的规格，不存在或已下架抛 SPEC_NOT_FOUND。"""
    spec = repo.get_active_by_code(db, code)
    if spec is None:
        raise AppError(ErrorCode.SPEC_NOT_FOUND)
    return spec


def _parse_cursor(cursor: str | None) -> tuple[int, int] | None:
    data = decode_cursor(cursor)
    if not data:
        return None
    s, i = data.get("s"), data.get("i")
    if isinstance(s, int) and isinstance(i, int):
        return s, i
    return None


def list_specs(db: Session, *, category: str | None, keyword: str | None, page: PageParams) -> SpecPage:
    rows = repo.list_active(
        db,
        category=category,
        keyword=keyword.strip() if keyword else None,
        after=_parse_cursor(page.cursor),
        limit=page.limit + 1,
    )
    has_more = len(rows) > page.limit
    rows = rows[: page.limit]
    next_cursor = encode_cursor({"s": rows[-1].sort, "i": rows[-1].id}) if has_more else None
    return SpecPage(items=[SpecOut.model_validate(r) for r in rows], next_cursor=next_cursor)


def get_spec_detail(db: Session, code: str) -> SpecDetail:
    spec = get_active_spec(db, code)
    return SpecDetail(
        **SpecOut.model_validate(spec).model_dump(),
        dpi=spec.dpi,
        bg_colors=spec.bg_colors,
        file_size_min_kb=spec.file_size_min_kb,
        file_size_max_kb=spec.file_size_max_kb,
        beauty_max=spec.beauty_max,
        form_schema=spec.form_schema,
        supports_receipt=repo.supports_receipt(db, spec.id),
        official_valid_days=spec.official_valid_days,
    )


def _load_catalog(adapter: str, provider_code: str) -> dict[str, ProviderItem]:
    catalog: dict[str, ProviderItem] = {}
    try:
        with open_catalog_provider(adapter, provider_code) as provider:
            for item in provider.list_items():
                if item.provider_item_id in catalog:
                    raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "回执服务商目录含重复规格编号")
                if item.file_size_min_kb is None or item.file_size_max_kb is None:
                    detail = provider.get_item(item.provider_item_id)
                    item = replace(
                        item,
                        file_size_min_kb=detail.file_size_min_kb,
                        file_size_max_kb=detail.file_size_max_kb,
                        sort=detail.sort,
                    )
                catalog[item.provider_item_id] = item
    except TimeoutError:
        pass
    else:
        return catalog
    raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "读取回执服务商规格目录超时")


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


def _create_catalog_spec(db: Session, provider_code: str, item: ProviderItem) -> Spec:
    prefix = {"zheying": "zy", "qianweiyun": "qwy"}.get(provider_code, provider_code)
    base = re.sub(r"[^a-z0-9_]+", "_", f"{prefix}_{item.provider_item_id}".lower())
    values = {
        **_photo_fields(item),
        "name": item.name,
        "category": "receipt",
        "cert_type": "unknown",
        "status": "inactive",
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
    spec: Spec, item_id: str, change: ProviderSyncChange, changed_fields: list[str] | None = None
) -> ProviderSyncItem:
    return ProviderSyncItem(
        provider_item_id=item_id,
        spec_code=spec.code,
        spec_name=spec.name,
        change=change,
        changed_fields=changed_fields or [],
    )


def sync_provider_specs(db: Session, provider_code: str) -> ProviderSyncResult:
    """读取全量目录后同步规格，保留运营配置。只 flush，由调用方提交。"""
    provider = repo.lock_catalog_provider(db, provider_code)
    if provider is None:
        raise AppError(ErrorCode.NOT_FOUND, "服务商不存在")
    catalog = _load_catalog(provider.adapter, provider_code)
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
        items.append(_sync_detail(spec, item_id, "updated" if changed else "unchanged", changed))

    # 历史上同一服务商规格可关联多个本地规格，例如同一规格的不同地区。上面会逐条更新。
    for item_id, item in sorted(catalog.items()):
        if item_id in seen:
            continue
        spec = _create_catalog_spec(db, provider_code, item)
        db.add(
            ProviderSpec(
                provider_id=provider.id,
                spec_id=spec.id,
                provider_item_id=item_id,
                is_enabled=False,
                cost_fen=0,
                param_mapping={},
                last_synced_at=synced_at,
            )
        )
        items.append(_sync_detail(spec, item_id, "created"))

    db.flush()
    return ProviderSyncResult(
        created=sum(item.change == "created" for item in items),
        updated=sum(item.change == "updated" for item in items),
        unchanged=sum(item.change == "unchanged" for item in items),
        disabled=sum(item.change == "disabled" for item in items),
        items=items,
    )
