from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.integrations.receipt_providers.fake import FakeProvider
from app.models import ProviderSpec, Spec
from app.modules.specs import service
from tests.factories import make_provider_for, make_spec


def test_sync_creates_updates_disables_and_is_idempotent(db: Session, monkeypatch):
    old = make_spec(db, "custom")
    old.name = "运营名称"
    old.category = "exam"
    old.sort = 99
    provider = make_provider_for(db, old, "zheying")
    existing = db.scalar(select(ProviderSpec).where(ProviderSpec.spec_id == old.id))
    assert existing is not None
    existing.param_mapping = {"name": "text_name"}
    db.add_all(
        [
            ProviderSpec(
                provider_id=provider.id,
                spec_id=make_spec(db, "regional").id,
                provider_item_id="713",
                cost_fen=500,
            ),
            ProviderSpec(
                provider_id=provider.id,
                spec_id=make_spec(db, "obsolete").id,
                provider_item_id="999",
                cost_fen=600,
            ),
        ]
    )
    occupied = make_spec(db, "zy_1001")
    db.flush()
    old_fields = (
        old.name,
        old.category,
        old.sort,
        old.status,
        old.form_schema,
        old.cert_type,
        old.beauty_max,
    )

    seen_at = datetime(2026, 11, 19, tzinfo=UTC)
    monkeypatch.setattr(service, "utcnow", lambda: seen_at)
    fake = FakeProvider("zheying")
    new_item = fake.get_item("1001")
    fake_row = replace(
        # 同一目录条目关联两个本地运营规格。
        new_item,
        provider_item_id="713",
        name="服务商名称",
        sort=2,
        file_size_max_kb=None,
    )
    monkeypatch.setattr(FakeProvider, "list_items", lambda _: [fake_row, new_item])
    details = []

    def get_item(_, item_id):
        details.append(item_id)
        return replace(fake_row, file_size_max_kb=80)

    monkeypatch.setattr(FakeProvider, "get_item", get_item)
    result = service.sync_provider_specs(db, provider.code)
    assert (result.created, result.updated, result.unchanged, result.disabled) == (1, 2, 0, 1)
    assert details == ["713"]
    assert (
        old.name,
        old.category,
        old.sort,
        old.status,
        old.form_schema,
        old.cert_type,
        old.beauty_max,
    ) == old_fields
    assert (old.width_px, old.height_px, old.bg_colors, old.file_size_max_kb) == (
        295,
        413,
        ["#438EDB", "#FFFFFF", "#FF0000"],
        80,
    )
    assert occupied.status == "active"
    created = next(item for item in result.items if item.change == "created")
    assert created.spec_code == "zy_1001_2"
    new_spec = db.scalar(select(Spec).where(Spec.code == created.spec_code))
    assert new_spec is not None
    assert (new_spec.status, new_spec.category, new_spec.cert_type) == ("inactive", "receipt", "unknown")
    rows = {row.spec_id: row for row in db.scalars(select(ProviderSpec))}
    new_row = rows[new_spec.id]
    assert (new_row.is_enabled, new_row.cost_fen, new_row.param_mapping) == (False, 0, {})
    assert (rows[old.id].cost_fen, rows[old.id].is_enabled) == (300, True)
    assert rows[old.id].param_mapping == {"name": "text_name"}
    assert all(not row.is_enabled for row in rows.values() if row.provider_item_id == "999")

    seen_at += timedelta(minutes=1)
    again = service.sync_provider_specs(db, provider.code)
    assert (again.created, again.updated, again.unchanged, again.disabled) == (0, 0, 3, 0)
    assert new_row.last_synced_at == rows[old.id].last_synced_at == seen_at

    reappeared = replace(new_item, provider_item_id="999")
    monkeypatch.setattr(FakeProvider, "list_items", lambda _: [fake_row, new_item, reappeared])
    result = service.sync_provider_specs(db, provider.code)
    assert (result.created, result.updated, result.unchanged, result.disabled) == (0, 1, 3, 0)
    assert all(not row.is_enabled for row in rows.values() if row.provider_item_id == "999")


def test_sync_failure_before_catalog_complete_leaves_existing_rows(db: Session, monkeypatch):
    spec = make_spec(db)
    provider = make_provider_for(db, spec, "zheying")
    fake = FakeProvider("zheying")
    new_item = fake.get_item("1001")
    incomplete = replace(fake.get_item("713"), file_size_min_kb=None)
    monkeypatch.setattr(FakeProvider, "list_items", lambda _: [new_item, incomplete])

    def timeout(*_):
        raise TimeoutError

    monkeypatch.setattr(FakeProvider, "get_item", timeout)
    with pytest.raises(AppError) as caught:
        service.sync_provider_specs(db, provider.code)
    assert caught.value.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert db.scalar(select(Spec).where(Spec.code == "zy_1001")) is None
    row = db.scalar(select(ProviderSpec).where(ProviderSpec.provider_id == provider.id))
    assert row.is_enabled and row.last_synced_at is None
