from types import SimpleNamespace

from app.core.pagination import PageIn, PageParams
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
