"""游标分页的公共工具，所有列表接口共用。

一个列表接口要做的事：
1. router 参数里写 `page: Page`（`app.core.deps.Page`），得到统一的 cursor / limit 查询参数；
   用 POST 请求体传筛选条件的（如后台用户搜索），请求体继承 `PageIn`，再用 `PageParams.of(body)`。
2. 返回模型用 `page_model(XxxOut, "XxxPage")`（`app.core.schemas`），统一为 {items, next_cursor}。
3. service 里：
       rows = repo.list_xxx(db, ..., before_id=page.before_id(), limit=page.fetch_limit)
       rows, next_cursor = page.slice(rows)
   排序不是按 id 倒序的，自己决定游标里放什么：
       after = page.cursor_values()          # 解析游标，非法或为空返回 None（从第一页开始）
       rows, next_cursor = page.slice(rows, cursor_of=lambda r: {"s": r.sort, "i": r.id})

游标对前端是不透明字符串，只能原样回传；内容格式改了也只会让旧游标回到第一页，不会报错。
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import Field

from app.core.schemas import Schema
from app.core.utils import decode_cursor, encode_cursor

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

CURSOR_DESCRIPTION = "翻页游标：第一页不传，之后原样传上一页返回的 next_cursor"
LIMIT_DESCRIPTION = f"每页条数，1～{MAX_LIMIT}，默认 {DEFAULT_LIMIT}"


def _by_id(row: Any) -> dict[str, Any]:
    return {"i": row.id}


@dataclass(frozen=True)
class PageParams:
    """一次翻页请求：游标 + 每页条数。"""

    cursor: str | None = None
    limit: int = DEFAULT_LIMIT

    @classmethod
    def of(cls, body: PageIn) -> PageParams:
        return cls(cursor=body.cursor, limit=body.limit)

    @property
    def fetch_limit(self) -> int:
        """查库时多取一条，用来判断还有没有下一页。"""
        return self.limit + 1

    def cursor_values(self) -> dict[str, Any] | None:
        """解析游标；为空或非法时返回 None，等同于第一页。"""
        return decode_cursor(self.cursor)

    def before_id(self) -> int | None:
        """按 id 倒序翻页时，本页要取 id 小于这个值的记录；第一页为 None。"""
        values = self.cursor_values()
        value = values.get("i") if values else None
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def slice[T](
        self, rows: list[T], cursor_of: Callable[[T], dict[str, Any]] = _by_id
    ) -> tuple[list[T], str | None]:
        """把多取一条的查询结果切成本页数据和下一页游标（没有下一页时为 None）。"""
        items = rows[: self.limit]
        if len(rows) > self.limit and items:
            return items, encode_cursor(cursor_of(items[-1]))
        return items, None


class PageIn(Schema):
    """用请求体翻页时的公共字段（POST 搜索类接口继承它）。"""

    cursor: str | None = Field(default=None, description=CURSOR_DESCRIPTION, examples=["eyJpIjoxMDI0fQ"])
    limit: int = Field(
        default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description=LIMIT_DESCRIPTION, examples=[20]
    )
