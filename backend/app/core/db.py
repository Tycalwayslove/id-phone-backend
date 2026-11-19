from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# pool_pre_ping：用连接前先探一下，服务器上数据库重启或连接被断开后能自动恢复
engine = create_engine(settings.database_url, echo=settings.db_echo, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


def get_db() -> Iterator[Session]:
    """每个请求一个数据库会话。事务由 service 层显式 commit；出错时自动回滚。"""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
