from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.integrations.receipt_providers.fake import FakeProvider
from app.models import Provider, ProviderSpec, RouteRule, Spec
from app.modules.receipts.service import _clean_form
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
    occupied = make_spec(db, "cat_zheying_1001")
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
    monkeypatch.setattr(FakeProvider, "get_item", lambda *_: pytest.fail("同步不请求详情"))
    result = service.sync_provider_specs(db, provider.code)
    assert (result.created, result.updated, result.unchanged, result.disabled) == (1, 2, 0, 1)
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
        None,
    )
    assert occupied.status == "active"
    created = next(item for item in result.items if item.change == "created")
    assert created.spec_code == "cat_zheying_1001_2"
    new_spec = db.scalar(select(Spec).where(Spec.code == created.spec_code))
    assert new_spec is not None
    assert (new_spec.status, new_spec.category, new_spec.cert_type) == ("active", "normal", "unknown")
    rows = {row.spec_id: row for row in db.scalars(select(ProviderSpec))}
    new_row = rows[new_spec.id]
    assert (new_row.is_enabled, new_row.cost_fen, new_row.param_mapping) == (True, 0, {})
    assert (rows[old.id].cost_fen, rows[old.id].is_enabled) == (300, True)
    assert rows[old.id].param_mapping == {"name": "text_name"}
    assert all(not row.is_enabled for row in rows.values() if row.provider_item_id == "999")

    rule = db.scalar(select(RouteRule).where(RouteRule.spec_id == new_spec.id))
    assert (rule.region_code, rule.priority, rule.is_enabled) == (None, 100, False)
    new_spec.status, new_spec.category, new_spec.region_code = "inactive", "exam", "440100"
    new_row.is_enabled, new_row.cost_fen = False, 123
    rule.priority, rule.is_enabled = 5, True
    seen_at += timedelta(minutes=1)
    again = service.sync_provider_specs(db, provider.code)
    assert (again.created, again.updated, again.unchanged, again.disabled) == (0, 0, 3, 0)
    assert new_row.last_synced_at == rows[old.id].last_synced_at == seen_at
    assert (new_spec.status, new_spec.category, new_spec.region_code) == ("inactive", "exam", "440100")
    assert (new_row.is_enabled, new_row.cost_fen, rule.priority, rule.is_enabled) == (False, 123, 5, True)

    reappeared = replace(new_item, provider_item_id="999")
    monkeypatch.setattr(FakeProvider, "list_items", lambda _: [fake_row, new_item, reappeared])
    result = service.sync_provider_specs(db, provider.code)
    assert (result.created, result.updated, result.unchanged, result.disabled) == (0, 1, 3, 0)
    assert all(not row.is_enabled for row in rows.values() if row.provider_item_id == "999")


def test_sync_failure_before_catalog_complete_leaves_existing_rows(db: Session, monkeypatch):
    spec = make_spec(db)
    provider = make_provider_for(db, spec, "zheying")

    def timeout(_):
        raise TimeoutError

    monkeypatch.setattr(FakeProvider, "list_items", timeout)
    with pytest.raises(AppError) as caught:
        service.sync_provider_specs(db, provider.code)
    assert caught.value.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert db.scalar(select(Spec).where(Spec.code == "cat_zheying_1001")) is None
    row = db.scalar(select(ProviderSpec).where(ProviderSpec.provider_id == provider.id))
    assert row.is_enabled and row.last_synced_at is None


def test_sync_matches_shared_upstream_then_normalized_name_and_size(db: Session, monkeypatch):
    zy = Provider(code="zheying", name="鹧应", adapter="zheying", upstream_group="shared")
    qwy = Provider(code="qianweiyun", name="黔微云", adapter="qianweiyun", upstream_group="shared")
    other = Provider(code="other", name="独立上游", adapter="fake")
    db.add_all([zy, qwy, other])
    db.flush()
    item = replace(
        FakeProvider("zheying").get_item("713"),
        name="广东省　身份证（回执）",
        receipt_fields=["text_name", "text_idcard", "text_mobile", "text_city", "text_unit"],
    )
    qwy_item = replace(item, name="黔微云名称", is_receipt=None, receipt_fields=[])
    other_item = replace(item, provider_item_id="9", name="广东省 身份证(回执)")
    distinct_size = replace(other_item, provider_item_id="10", width_px=500)
    exam = replace(item, provider_item_id="12", name="四川报名照", is_receipt=False, receipt_fields=[])
    catalogs = {zy.code: [item], qwy.code: [qwy_item], other.code: [other_item, distinct_size, exam]}
    monkeypatch.setattr(FakeProvider, "list_items", lambda self: catalogs[self.code])

    first = service.sync_provider_specs(db, zy.code)
    assert first.created == 1
    assert first.items[0].unknown_receipt_fields == ["text_unit"]
    spec = db.scalar(select(Spec).where(Spec.code == "cat_shared_713"))
    assert (spec.status, spec.category, spec.region_code) == ("active", "receipt", "440000")
    assert [(field["key"], field["label"], field["required"]) for field in spec.form_schema] == [
        ("name", "姓名", True),
        ("idcard", "身份证号", True),
        ("mobile", "手机号", True),
        ("city", "所在城市", True),
        ("text_unit", "text_unit", True),
    ]
    with pytest.raises(AppError, match="身份证号格式不正确"):
        _clean_form(
            spec,
            {
                "name": "测试",
                "idcard": "invalid",
                "mobile": "13000000000",
                "city": "广州",
                "text_unit": "测试",
            },
        )

    assert service.sync_provider_specs(db, qwy.code).items[0].spec_code == spec.code
    last = service.sync_provider_specs(db, other.code, auto_publish=False)
    assert {row.provider_item_id: row.spec_code for row in last.items} == {
        "9": spec.code,
        "10": "cat_other_10",
        "12": "cat_other_12",
    }
    assert spec.status == "active"
    exam_spec = db.scalar(select(Spec).where(Spec.code == "cat_other_12"))
    assert (exam_spec.status, exam_spec.category, exam_spec.region_code) == ("inactive", "exam", "510000")
    rows = {
        row.provider_id: row
        for row in db.scalars(select(ProviderSpec).where(ProviderSpec.spec_id == spec.id))
    }
    assert rows[zy.id].param_mapping == {
        "name": "text_name",
        "idcard": "text_idcard",
        "mobile": "text_mobile",
        "city": "text_city",
        "text_unit": "text_unit",
    }
    assert rows[qwy.id].param_mapping == rows[other.id].param_mapping == rows[zy.id].param_mapping
    assert rows[zy.id].is_enabled and rows[qwy.id].is_enabled and not rows[other.id].is_enabled
    rules = list(db.scalars(select(RouteRule).where(RouteRule.spec_id == spec.id)))
    assert {rule.provider_id for rule in rules} == {zy.id, qwy.id}
    assert all(rule.is_enabled and rule.priority == 100 and rule.region_code is None for rule in rules)

    service.sync_provider_specs(db, other.code)
    assert not rows[other.id].is_enabled and exam_spec.status == "inactive"
    assert db.scalar(select(RouteRule).where(RouteRule.provider_id == other.id)) is None


def test_sync_catalog_logs_one_unknown_color_count(monkeypatch, caplog):
    fake = FakeProvider("zheying")
    first, second = (replace(fake.get_item(code), unknown_color_count=2) for code in ("1001", "1002"))
    monkeypatch.setattr(FakeProvider, "list_items", lambda _: [first, second])

    assert list(service._load_catalog("zheying", "zheying")) == ["1001", "1002"]
    assert [record.getMessage() for record in caplog.records] == ["回执服务商目录已跳过 4 个未知底色"]


def test_sync_result_does_not_depend_on_provider_order(db: Session, monkeypatch):
    """黔微云列表不带回执标记和办理字段；先同步哪家，最终结果都必须一样。"""
    fake = FakeProvider("zheying")
    base_receipt, base_normal = fake.get_item("713"), fake.get_item("1001")  # 替换 list_items 之前取样例
    catalogs: dict[str, list] = {}
    monkeypatch.setattr(FakeProvider, "list_items", lambda self: catalogs[self.code])

    def run(tag: str, order: tuple[str, str]) -> dict:
        zy = Provider(code=f"zy_{tag}", name="鹧应", adapter="zheying", upstream_group=f"g_{tag}")
        qwy = Provider(code=f"qwy_{tag}", name="黔微云", adapter="qianweiyun", upstream_group=f"g_{tag}")
        db.add_all([zy, qwy])
        db.flush()
        # 名称带 tag，避免两轮之间按名称和尺寸合并
        receipt = replace(base_receipt, name=f"广州市身份证{tag}")
        normal = replace(base_normal, name=f"一寸{tag}")
        catalogs[zy.code] = [receipt, normal]
        catalogs[qwy.code] = [
            replace(item, is_receipt=None, receipt_fields=[], provider_category=None)
            for item in (receipt, normal)
        ]
        roles = {"zy": zy, "qwy": qwy}
        for role in order:
            service.sync_provider_specs(db, roles[role].code)

        snapshot = {}
        for item_id in ("713", "1001"):
            spec = db.scalar(select(Spec).where(Spec.code == f"cat_g_{tag}_{item_id}"))
            assert spec is not None, item_id
            mappings = {
                row.provider_id: row.param_mapping
                for row in db.scalars(select(ProviderSpec).where(ProviderSpec.spec_id == spec.id))
            }
            routes = {
                rule.provider_id: rule.is_enabled
                for rule in db.scalars(select(RouteRule).where(RouteRule.spec_id == spec.id))
            }
            snapshot[item_id] = {
                "category": spec.category,
                "status": spec.status,
                "region": spec.region_code,
                "form": [field["key"] for field in spec.form_schema],
                "mapping": {role: mappings.get(p.id) for role, p in roles.items()},
                "route": {role: routes.get(p.id) for role, p in roles.items()},
            }
        return snapshot

    zheying_first = run("a", ("zy", "qwy"))
    qianweiyun_first = run("b", ("qwy", "zy"))
    assert zheying_first == qianweiyun_first

    receipt = zheying_first["713"]
    assert (receipt["category"], receipt["status"], receipt["region"]) == ("receipt", "active", "440100")
    assert receipt["form"] == ["mobile", "city", "name", "idcard"]
    assert receipt["mapping"]["zy"] == receipt["mapping"]["qwy"] != {}
    assert receipt["route"] == {"zy": True, "qwy": True}
    normal = zheying_first["1001"]
    assert normal["category"] == "normal" and normal["route"] == {"zy": False, "qwy": False}


def test_sync_continues_when_sibling_catalog_fails(db: Session, monkeypatch, caplog):
    zy = Provider(code="zy_down", name="鹧应", adapter="zheying", upstream_group="g_down")
    qwy = Provider(code="qwy_down", name="黔微云", adapter="qianweiyun", upstream_group="g_down")
    db.add_all([zy, qwy])
    db.flush()
    item = replace(FakeProvider("zheying").get_item("713"), is_receipt=None, receipt_fields=[])

    def list_items(self):
        if self.code == zy.code:
            raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "down")
        return [item]

    monkeypatch.setattr(FakeProvider, "list_items", list_items)
    result = service.sync_provider_specs(db, qwy.code)
    assert result.created == 1
    assert "zy_down" in caplog.text
