"""将开发库规格的英文底色名转换为十六进制色值。

在 backend 目录运行：uv run python -m scripts.fix_spec_bg_colors [--apply]
"""

import argparse

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.integrations.receipt_providers._catalog import _COLORS
from app.models import Spec
from scripts.seed_dev import guard_dev_database


def convert_bg_colors(colors: list[str]) -> list[str]:
    """替换已知英文名，保留已有色值、未知颜色和顺序。"""
    return [_COLORS.get(color.strip().lower(), color) for color in colors]


def fix_spec_bg_colors(db: Session, *, apply: bool) -> int:
    if not db.scalar(text("SELECT current_database()")).endswith("_dev"):
        raise SystemExit("拒绝运行：实际连接的数据库名必须以 _dev 结尾。")

    stmt = select(Spec).order_by(Spec.id)
    if apply:
        stmt = stmt.with_for_update(key_share=True)

    changed = 0
    for spec in db.scalars(stmt):
        colors = convert_bg_colors(spec.bg_colors)
        if colors == spec.bg_colors:
            continue
        print(f"{spec.code}: {spec.bg_colors} → {colors}")
        if apply:
            spec.bg_colors = colors
        changed += 1
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="写入修改，省略时只打印计划")
    args = parser.parse_args()
    guard_dev_database()

    with SessionLocal() as db:
        changed = fix_spec_bg_colors(db, apply=args.apply)
        if args.apply:
            db.commit()
    print(f"{'已更新' if args.apply else '计划更新'} {changed} 条规格。")


if __name__ == "__main__":
    main()
