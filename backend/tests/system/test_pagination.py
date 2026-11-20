from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import column, create_engine, select, table
from sqlalchemy.orm import Session

from app.core.deps import Paging
from app.core.pagination import OffsetPageIn, OffsetPageParams, PageIn, PageParams, paginate
from app.core.utils import decode_cursor, encode_cursor


def _rows(*ids: int) -> list[SimpleNamespace]:
    return [SimpleNamespace(id=i) for i in ids]


def test_slice_detects_next_page_from_extra_row():
    page = PageParams(limit=2)
    assert page.fetch_limit == 3
    items, cursor = page.slice(_rows(9, 8, 7))
    assert [r.id for r in items] == [9, 8]
    assert PageParams(cursor=cursor).before_id() == 8

    items, cursor = page.slice(_rows(9, 8))
    assert [r.id for r in items] == [9, 8] and cursor is None
    assert page.slice([]) == ([], None)


def test_custom_cursor_and_invalid_cursor():
    page = PageParams(limit=1)
    _, cursor = page.slice(
        [SimpleNamespace(id=3, sort=5), SimpleNamespace(id=4, sort=6)],
        cursor_of=lambda r: {"s": r.sort, "i": r.id},
    )
    assert decode_cursor(cursor) == {"s": 5, "i": 3}

    for bad in (
        None,
        "",
        "bad!",
        encode_cursor({"i": "7"}),
        encode_cursor({"i": True}),
        encode_cursor({"x": 1}),
    ):
        assert PageParams(cursor=bad).before_id() is None


def test_page_in_body_converts_to_params():
    body = PageIn(cursor="abc", limit=50)
    assert PageParams.of(body) == PageParams(cursor="abc", limit=50)
    assert PageParams.of(PageIn()) == PageParams(cursor=None, limit=20)


def test_offset_pagination_counts_filtered_rows():
    records = table("records", column("id"), column("active"))
    engine = create_engine("sqlite://")
    with Session(engine) as db:
        db.connection().exec_driver_sql("CREATE TABLE records (id INTEGER PRIMARY KEY, active INTEGER)")
        db.execute(records.insert(), [{"id": i, "active": i <= 23} for i in range(1, 29)])
        stmt = select(records.c.id).where(records.c.active == 1).order_by(records.c.id.desc())

        second = OffsetPageParams(page=2, page_size=10)
        assert second.offset == 10
        assert paginate(db, stmt, second) == ([(i,) for i in range(13, 3, -1)], 23)
        assert paginate(db, stmt, OffsetPageParams(page=4, page_size=10)) == ([], 23)
        assert paginate(db, stmt.where(records.c.id < 0), OffsetPageParams()) == ([], 0)
    engine.dispose()


@pytest.fixture
def paging_client():
    app = FastAPI()

    @app.get("/")
    def from_query(page: Paging):
        return page

    @app.post("/")
    def from_body(body: OffsetPageIn):
        return body

    return TestClient(app)


def test_offset_paging_defaults_and_choices(paging_client):
    assert paging_client.get("/").json() == {"page": 1, "page_size": 20}
    assert paging_client.post("/", json={}).json() == {"page": 1, "page_size": 20}
    for size in (10, 20, 50, 100):
        params = {"page": 2, "page_size": size}
        assert paging_client.get("/", params=params).json() == params
        assert paging_client.post("/", json=params).json() == params


@pytest.mark.parametrize(
    "invalid",
    [{"page": 0}, {"page": -1}, {"page": 1.5}, {"page_size": 1}, {"page_size": 30}, {"page_size": 101}],
)
def test_offset_paging_rejects_invalid_query_and_body(paging_client, invalid):
    assert paging_client.get("/", params=invalid).status_code == 422
    assert paging_client.post("/", json=invalid).status_code == 422
