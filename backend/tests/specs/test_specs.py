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


def test_detail_not_found(client, db):
    r = client.get("/api/v1/specs/no_such_spec")
    assert r.status_code == 404
    assert r.json()["code"] == "SPEC_NOT_FOUND"

    s = make_spec(db, "det_off")
    s.status = "inactive"
    db.flush()
    assert client.get("/api/v1/specs/det_off").json()["code"] == "SPEC_NOT_FOUND"
