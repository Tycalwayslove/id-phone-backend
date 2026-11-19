"""规格业务：只读，不需要提交事务。"""

from sqlalchemy.orm import Session

from app.core.deps import PageParams
from app.core.errors import AppError, ErrorCode
from app.core.utils import decode_cursor, encode_cursor
from app.models import Spec
from app.modules.specs import repo
from app.modules.specs.schemas import SpecDetail, SpecOut, SpecPage


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
