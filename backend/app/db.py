from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

# pool_pre_ping：用连接前先探一下，服务器上数据库重启或连接被断开后能自动恢复
engine = create_engine(settings.database_url, echo=settings.db_echo, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
