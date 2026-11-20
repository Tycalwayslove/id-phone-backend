from sqlalchemy import update

from app.models import ProviderSpec, RouteRule
from app.modules.specs import repo
from tests.factories import make_provider_for, make_spec


def test_list_filters_and_excludes_inactive(client, db):
    make_spec(db, "flt_a", category="normal")
    make_spec(db, "flt_b", category="exam")
    off = make_spec(db, "flt_off", category="normal")
    off.status = "inactive"
    db.flush()

    r = client.get("/api/v1/specs", params={"keyword": "flt_"})
    assert r.status_code == 200
    assert [i["code"] for i in r.json()["items"]] == ["flt_a", "flt_b"]

    r = client.get("/api/v1/specs", params={"keyword": "flt_", "category": "exam"})
    assert [i["code"] for i in r.json()["items"]] == ["flt_b"]

    # 非法分类参数
    assert client.get("/api/v1/specs", params={"category": "xxx"}).status_code == 422


def test_list_keyword_escapes_like_wildcards(client, db):
    make_spec(db, "esc_x")
    # % 不应被当成通配符
    r = client.get("/api/v1/specs", params={"keyword": "%"})
    assert r.status_code == 200
    assert all("%" in i["name"] for i in r.json()["items"])


def test_list_pagination_by_sort_and_id(client, db):
    a = make_spec(db, "pg_1")
    b = make_spec(db, "pg_2")
    c = make_spec(db, "pg_3")
    a.sort, b.sort, c.sort = 5, 1, 1  # 期望顺序：pg_2, pg_3（sort 相同按 id）, pg_1
    db.flush()

    r1 = client.get("/api/v1/specs", params={"keyword": "pg_", "limit": 2}).json()
    assert [i["code"] for i in r1["items"]] == ["pg_2", "pg_3"]
    assert r1["next_cursor"]
    r2 = client.get(
        "/api/v1/specs", params={"keyword": "pg_", "limit": 2, "cursor": r1["next_cursor"]}
    ).json()
    assert [i["code"] for i in r2["items"]] == ["pg_1"]
    assert r2["next_cursor"] is None


def test_detail_and_supports_receipt(client, db):
    spec = make_spec(db, "det_a")
    r = client.get("/api/v1/specs/det_a")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == "det_a"
    assert body["width_px"] == 358
    assert body["bg_colors"] == ["#FFFFFF", "#438EDB"]
    assert body["beauty_max"] == 3
    assert [f["key"] for f in body["form_schema"]] == ["name", "idcard"]
    assert body["supports_receipt"] is False

    make_provider_for(db, spec)
    assert client.get("/api/v1/specs/det_a").json()["supports_receipt"] is True


def test_list_checks_receipt_support_in_one_batch(client, db, monkeypatch):
    available = make_spec(db, "receipt_check_yes")
    no_channel = make_spec(db, "receipt_check_no_channel")
    disabled_mapping = make_spec(db, "receipt_check_mapping")
    disabled_rule = make_spec(db, "receipt_check_rule")
    unavailable_provider = make_spec(db, "receipt_check_provider")
    make_provider_for(db, available, "receipt_check_yes")
    make_provider_for(db, disabled_mapping, "receipt_check_mapping")
    make_provider_for(db, disabled_rule, "receipt_check_rule")
    provider = make_provider_for(db, unavailable_provider, "receipt_check_provider")
    provider.status = "circuit_open"
    db.execute(
        update(ProviderSpec).where(ProviderSpec.spec_id == disabled_mapping.id).values(is_enabled=False)
    )
    db.execute(update(RouteRule).where(RouteRule.spec_id == disabled_rule.id).values(is_enabled=False))
    db.flush()

    calls = []
    receipt_spec_ids = repo.receipt_spec_ids

    def capture_batch(session, spec_ids):
        calls.append(spec_ids)
        return receipt_spec_ids(session, spec_ids)

    monkeypatch.setattr(repo, "receipt_spec_ids", capture_batch)
    response = client.get("/api/v1/specs", params={"keyword": "receipt_check_"})
    assert response.status_code == 200
    assert calls == [
        [available.id, no_channel.id, disabled_mapping.id, disabled_rule.id, unavailable_provider.id]
    ]
    assert {row["code"]: row["supports_receipt"] for row in response.json()["items"]} == {
        available.code: True,
        no_channel.code: False,
        disabled_mapping.code: False,
        disabled_rule.code: False,
        unavailable_provider.code: False,
    }


def test_detail_not_found(client, db):
    r = client.get("/api/v1/specs/no_such_spec")
    assert r.status_code == 404
    assert r.json()["code"] == "SPEC_NOT_FOUND"

    s = make_spec(db, "det_off")
    s.status = "inactive"
    db.flush()
    assert client.get("/api/v1/specs/det_off").json()["code"] == "SPEC_NOT_FOUND"


def test_list_by_city_and_province(client, db):
    for code, region in [
        ("area_all", None),
        ("area_gd", "440000"),
        ("area_gz", "440100"),
        ("area_sz", "440300"),
        ("area_bj", "110000"),
    ]:
        make_spec(db, code).region_code = region
    db.flush()

    def areas(**params):
        r = client.get("/api/v1/specs", params={"keyword": "area_", **params})
        assert r.status_code == 200
        return [(row["code"], row["region_name"]) for row in r.json()["items"]]

    assert areas(region_code="440100") == [("area_all", None), ("area_gd", "广东省"), ("area_gz", "广州市")]
    assert areas(region_code="440000") == [("area_all", None), ("area_gd", "广东省")]
    assert areas(region_code="national") == [("area_all", None)]
    assert len(areas()) == 5
    assert client.get("/api/v1/specs", params={"region_code": "foo"}).status_code == 422
    assert client.get("/api/v1/specs/area_gz").json()["region_name"] == "广州市"


def test_spec_regions_lists_only_active_regional_specs(client, db):
    for index, code in enumerate(["440000", "440100", "440100", "510100", "110000", None, "999999"]):
        make_spec(db, f"region_{index}").region_code = code
    disabled = make_spec(db, "region_disabled")
    disabled.region_code, disabled.status = "440300", "inactive"
    db.flush()

    response = client.get("/api/v1/spec-regions")
    assert response.status_code == 200
    regions = {row["region_code"]: row for row in response.json()}
    assert regions["440000"] == {
        "region_code": "440000",
        "region_name": "广东省",
        "spec_count": 3,
        "province_spec_count": 1,
        "cities": [{"region_code": "440100", "region_name": "广州市", "spec_count": 2}],
    }
    assert regions["510000"]["cities"] == [
        {"region_code": "510100", "region_name": "成都市", "spec_count": 1}
    ]
    assert regions["510000"]["province_spec_count"] == 0
    assert regions["110000"]["cities"] == [] and regions["110000"]["province_spec_count"] == 1
    assert "999999" not in regions
