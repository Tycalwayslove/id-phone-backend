from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import engine


def database_is_up() -> bool:
    """执行一条最简单的查询，判断数据库能不能用。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True
