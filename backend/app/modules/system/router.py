from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.errors import ErrorResponse, error_doc
from app.modules.system import service
from app.modules.system.schemas import HealthResponse

router = APIRouter(tags=["系统"])


@router.get(
    "/health",
    operation_id="system_health",
    summary="健康检查",
    description="检查服务和数据库是否可用。部署平台和监控用它判断服务是否存活。不需要登录。",
    response_model=HealthResponse,
    response_description="服务和数据库都正常",
    responses={503: error_doc("数据库连不上，错误码 DB_UNAVAILABLE")},
)
def health():
    if not service.database_is_up():
        body = ErrorResponse(code="DB_UNAVAILABLE", message="数据库暂时不可用，请稍后再试")
        return JSONResponse(status_code=503, content=body.model_dump())
    return HealthResponse(status="ok", database="ok")
