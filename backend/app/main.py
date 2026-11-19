from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.config import settings
from app.modules.system.router import router as system_router


def _missing_operation_id(route: APIRoute) -> str:
    # 没写 operation_id 的接口会得到这个标记，scripts/check_api_docs.py 会把它查出来
    return f"MISSING_OPERATION_ID__{route.name}"


# 每个 tag 在 Apifox 里是一个目录，这里写清楚目录的用途
TAGS = [
    {"name": "系统", "description": "健康检查等运维接口，不需要登录"},
]

# 生产环境不公开接口文档页面；文档通过 CI 同步到 Apifox
_docs = not settings.is_prod
app = FastAPI(
    title="证件照与回执 API",
    description="证件照制作、回执办理、权益和订单相关接口。错误统一返回 `{code, message}`。",
    version="0.1.0",
    openapi_tags=TAGS,
    generate_unique_id_function=_missing_operation_id,
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)

app.include_router(system_router)
