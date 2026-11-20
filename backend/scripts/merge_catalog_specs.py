"""预览或合并开发库中 T019 创建的同上游重复规格。

在 backend 目录运行：uv run python -m scripts.merge_catalog_specs [--apply]
"""

import argparse
import re
from collections import defaultdict

from sqlalchemy import or_, select, text, union
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import PhotoRender, Provider, ProviderSpec, ReceiptApplication, RouteRule, Spec
from app.modules.specs.repo import lock_catalog_merge
from scripts.seed_dev import guard_dev_database

_LEGACY_PREFIXES = {"zheying": "zy", "qianweiyun": "qwy"}


def _groups(db: Session) -> dict[tuple[str, str], list[Spec]]:
    stmt = (
        select(Spec, ProviderSpec.provider_item_id, Provider.code, Provider.upstream_group)
        .join(ProviderSpec, ProviderSpec.spec_id == Spec.id)
        .join(Provider, Provider.id == ProviderSpec.provider_id)
        .where(
            or_(Spec.code.startswith("zy_", autoescape=True), Spec.code.startswith("qwy_", autoescape=True)),
            Provider.code.in_(_LEGACY_PREFIXES),
            Provider.upstream_group != "",
        )
        .order_by(Spec.id)
    )
    groups = defaultdict(list)
    for spec, item_id, provider_code, group in db.execute(stmt):
        prefix = _LEGACY_PREFIXES[provider_code]
        base = re.sub(r"[^a-z0-9_]+", "_", f"{prefix}_{item_id}".lower())
        suffix = re.search(r"_[0-9]+$", spec.code)
        # T019 只会使用清洗并截断过的编码，或在其后加冲突序号。
        if spec.code == base[:64] or (
            suffix and int(suffix[0][1:]) >= 2 and spec.code == base[: 64 - len(suffix[0])] + suffix[0]
        ):
            groups[group, item_id].append(spec)
    return {key: specs for key, specs in groups.items() if len(specs) > 1}


def _referenced_specs(db: Session, ids: set[int]) -> set[int]:
    return set(
        db.scalars(
            union(
                select(PhotoRender.spec_id).where(PhotoRender.spec_id.in_(ids)),
                select(ReceiptApplication.spec_id).where(ReceiptApplication.spec_id.in_(ids)),
                select(Spec.parent_id).where(Spec.parent_id.in_(ids)),
            )
        )
    )


def merge_catalog_specs(db: Session, *, apply: bool) -> int:
    """打印合并计划，按需执行；事务由调用方提交。"""
    if not db.scalar(text("SELECT current_database()")).endswith("_dev"):
        raise SystemExit("拒绝运行：实际连接的数据库名必须以 _dev 结尾。")
    if apply:
        lock_catalog_merge(db)
        db.execute(text("LOCK TABLE specs, provider_specs, route_rules IN SHARE ROW EXCLUSIVE MODE"))
    groups = _groups(db)
    ids = {spec.id for specs in groups.values() for spec in specs}
    if not ids:
        return 0
    if apply:
        # 阻止新导出和回执在检查引用后关联待删除的规格。
        db.execute(select(Spec.id).where(Spec.id.in_(ids)).order_by(Spec.id).with_for_update()).all()
    referenced = _referenced_specs(db, ids)
    mappings = defaultdict(dict)
    for row in db.scalars(select(ProviderSpec).where(ProviderSpec.spec_id.in_(ids))):
        mappings[row.spec_id][row.provider_id] = row
    rules = defaultdict(dict)
    for rule in db.scalars(select(RouteRule).where(RouteRule.spec_id.in_(ids))):
        rules[rule.spec_id][rule.provider_id, rule.region_code] = rule

    merged = 0
    for (group, item_id), specs in sorted(groups.items()):
        # 优先保留已有业务引用的规格，其次保留运营已上架的规格。
        target, *duplicates = sorted(
            specs, key=lambda s: (s.id not in referenced, s.status != "active", s.id)
        )
        target_mappings, target_rules = mappings[target.id], rules[target.id]
        for source in duplicates:
            if source.id in referenced:
                print(f"跳过仍有导出、回执或子规格引用的 {source.code}")
                continue
            source_mappings = mappings[source.id]
            if any(
                provider_id in target_mappings
                and target_mappings[provider_id].provider_item_id != row.provider_item_id
                for provider_id, row in source_mappings.items()
            ):
                print(f"跳过 {source.code}，其服务商编号与 {target.code} 冲突")
                continue
            move_mappings = {key: row for key, row in source_mappings.items() if key not in target_mappings}
            move_rules = {key: row for key, row in rules[source.id].items() if key not in target_rules}
            print(
                f"{group}/{item_id}：{source.code} → {target.code}，转移 {len(move_mappings)} 条映射、"
                f"{len(move_rules)} 条路由，保留目标已有配置，删除 {source.code}"
            )
            target_mappings.update(move_mappings)
            target_rules.update(move_rules)
            merged += 1
            if apply:
                for row in [*move_mappings.values(), *move_rules.values()]:
                    row.spec_id = target.id
                db.flush()
                db.delete(source)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="执行合并。默认仅打印计划。")
    args = parser.parse_args()
    guard_dev_database()
    with SessionLocal.begin() as db:
        count = merge_catalog_specs(db, apply=args.apply)
    print(f"{'已合并' if args.apply else '计划合并'} {count} 条重复规格。")


if __name__ == "__main__":
    main()
