from fastapi import FastAPI
from sqlalchemy import text

from app.config import settings
from app.db import engine

# 生产环境不公开接口文档页面；文档通过 CI 同步到 Apifox
_docs = not settings.is_prod
app = FastAPI(
    title="id-phone API",
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
