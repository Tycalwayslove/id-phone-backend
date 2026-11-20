"""列表接口的游标和页码分页工具。

一个列表接口要做的事：
1. router 参数里写 `page: Page`（`app.core.deps.Page`），得到统一的 cursor / limit 查询参数；
   用 POST 请求体传筛选条件的，请求体继承 `PageIn`，再用 `PageParams.of(body)`。
2. 返回模型用 `page_model(XxxOut, "XxxPage")`（`app.core.schemas`），统一为 {items, next_cursor}。
3. service 里：
       rows = repo.list_xxx(db, ..., before_id=page.before_id(), limit=page.fetch_limit)
       rows, next_cursor = page.slice(rows)
   排序不是按 id 倒序的，自己决定游标里放什么：
       after = page.cursor_values()          # 解析游标，非法或为空返回 None（从第一页开始）
       rows, next_cursor = page.slice(rows, cursor_of=lambda r: {"s": r.sort, "i": r.id})

游标对前端是不透明字符串，只能原样回传；内容格式改了也只会让旧游标回到第一页，不会报错。

后台列表使用 `page: Paging` 或继承 `OffsetPageIn`，返回 `offset_page_model` 生成的模型。
查询先加筛选与包含唯一键的排序，再交给 `paginate`。
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import Field, create_model
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

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


PageSize = Literal[10, 20, 50, 100]
DEFAULT_PAGE_SIZE: PageSize = 20
PAGE_DESCRIPTION = "页码从 1 开始，默认 1。超过最后一页时返回空列表"
PAGE_SIZE_DESCRIPTION = "每页条数，只能选 10、20、50 或 100，默认 20"


class OffsetPageParams(Schema):
    """后台列表的页码和每页条数。"""

    page: int = Field(default=1, ge=1, description=PAGE_DESCRIPTION, examples=[2])
    page_size: PageSize = Field(default=DEFAULT_PAGE_SIZE, description=PAGE_SIZE_DESCRIPTION, examples=[20])

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class OffsetPageIn(OffsetPageParams):
    """后台 POST 搜索接口请求体的公共分页字段。"""


def offset_page_model(item: type[Schema], name: str, order: str = "按记录 ID 从大到小") -> Any:
    """生成后台页码分页返回模型。"""
    first_line = (item.__doc__ or name).strip().splitlines()[0]
    return create_model(
        name,
        __base__=Schema,
        __doc__=f"页码分页列表：{first_line}",
        items=(list[item], Field(description=f"本页数据，{order}。超出最后一页时返回空列表")),
        total=(int, Field(ge=0, description="符合筛选条件的记录总条数", examples=[42])),
        page=(int, Field(ge=1, description="请求的页码，从 1 开始", examples=[2])),
        page_size=(PageSize, Field(description="请求的每页条数，可选 10、20、50 或 100", examples=[20])),
    )


def paginate[*Cols](
    db: Session, stmt: Select[*Cols], params: OffsetPageParams
) -> tuple[list[tuple[*Cols]], int]:
    """对未分页的筛选查询计数，再取排序后的单页记录。"""
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    if params.offset >= total:
        return [], total
    rows = db.execute(stmt.offset(params.offset).limit(params.page_size))
    return [cast("tuple[*Cols]", tuple(row)) for row in rows], total
