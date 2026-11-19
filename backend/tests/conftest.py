"""测试公共设施。

- 测试连真实的 PostgreSQL（CI 里是临时数据库 idphone_test，已执行过 alembic upgrade head）。
- 每个测试在一个事务里跑，结束后整体回滚，测试之间互不影响；业务代码里的 commit 只提交到保存点。
- 外部服务全部是 fake 模式（见 app/integrations）。
"""

import os
import tempfile

os.environ["APP_ENV"] = "test"
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/idphone_test")
os.environ["LOCAL_STORAGE_DIR"] = tempfile.mkdtemp(prefix="idphone-test-")
os.environ["WECHAT_MODE"] = "fake"
os.environ["PAY_MODE"] = "fake"
os.environ["RECEIPT_MODE"] = "fake"
os.environ["STORAGE_MODE"] = "local"

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.db import engine, get_db
from app.main import app


@pytest.fixture
def db() -> Iterator[Session]:
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        conn.close()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def login(client: TestClient, code: str = "dev:alice") -> dict[str, str]:
    """用假微信登录，返回带令牌的请求头。依赖 auth 模块的 POST /api/v1/auth/wechat-mini/login。"""
    r = client.post("/api/v1/auth/wechat-mini/login", json={"code": code})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
