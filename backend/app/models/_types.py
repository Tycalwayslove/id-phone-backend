"""模型里反复用到的小工具。"""

from sqlalchemy import CheckConstraint


def check_in(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    """生成 “column IN (...)” 的 CHECK 约束，用来代替数据库枚举类型。

    以后新增一个状态值，只需要改这里的元组并生成一次迁移。
    """
    quoted = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({quoted})", name=name)
