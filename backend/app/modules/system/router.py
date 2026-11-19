import mimetypes
import time
from typing import Annotated

from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse, Response

from app.core.errors import AppError, ErrorCode, ErrorResponse, errors_doc
from app.integrations.storage import get_storage, url_signature
from app.modules.system import service
from app.modules.system.schemas import HealthResponse

router = APIRouter(tags=["系统"])
files_router = APIRouter(tags=["系统"])


@router.get(
    "/health",
    operation_id="system_health",
    summary="健康检查",
    description="检查服务和数据库是否可用。部署平台和监控用它判断服务是否存活。不需要登录。",
    response_model=HealthResponse,
    response_description="服务和数据库都正常",
    responses=errors_doc(ErrorCode.DB_UNAVAILABLE),
)
def health():
    if not service.database_is_up():
        body = ErrorResponse(code=ErrorCode.DB_UNAVAILABLE, message="数据库暂时不可用，请稍后再试")
        return JSONResponse(status_code=503, content=body.model_dump(exclude_none=True))
    return HealthResponse(status="ok", database="ok")


@files_router.get(
    "/files/{key:path}",
    operation_id="system_file_download",
    summary="下载文件（签名链接）",
    description=(
        "本机存储模式下的文件下载地址。链接由其他接口生成（如照片下载、回执查看），带有效期和签名，"
        "前端直接用于 image 组件或 wx.downloadFile，不需要自己拼。过期或签名不对返回 404。"
    ),
    response_class=Response,
    response_description="文件内容（图片二进制）",
    responses=errors_doc(ErrorCode.NOT_FOUND),
)
def download_file(
    key: Annotated[str, Path(description="文件存储路径，由接口返回的链接自带")],
    exp: Annotated[int, Query(description="链接过期时间（Unix 秒）")],
    sig: Annotated[str, Query(description="链接签名")],
):
    if exp < time.time() or sig != url_signature(key, exp):
        raise AppError(ErrorCode.NOT_FOUND)
    try:
        data = get_storage().get(key)
    except (FileNotFoundError, ValueError) as e:
        raise AppError(ErrorCode.NOT_FOUND) from e
    mime = mimetypes.guess_type(key)[0] or "application/octet-stream"
    return Response(content=data, media_type=mime, headers={"Cache-Control": "private, max-age=300"})
