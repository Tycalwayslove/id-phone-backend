from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import PlainTextResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.core.deps import DB, Me, Page
from app.core.errors import AppError, ErrorCode, errors_doc
from app.core.schemas import OkResponse
from app.modules.photos import service
from app.modules.photos.schemas import (
    DownloadOut,
    PhotoCreate,
    PhotoDetail,
    PhotoOut,
    PhotoPage,
    RenderCreate,
    RenderOut,
    UploadOut,
    WechatMediaEvent,
)

router = APIRouter(tags=["照片"])
callback_router = APIRouter(tags=["回调"])

_AUTH = (ErrorCode.AUTH_REQUIRED, ErrorCode.AUTH_INVALID)
_MAX_ID = 9223372036854775807

PhotoId = Annotated[int, Path(ge=1, le=_MAX_ID, description="照片 ID", examples=[12])]
RenderId = Annotated[int, Path(ge=1, le=_MAX_ID, description="导出图 ID", examples=[7])]

# 文件上传由路由函数自己读 multipart（避免框架自动生成没有说明的匿名模型），文档在这里手写
_UPLOAD_BODY = {
    "requestBody": {
        "required": True,
        "description": "multipart/form-data，只有一个文件字段 file",
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "file": {
                            "type": "string",
                            "format": "binary",
                            "description": "图片文件，JPEG 或 PNG，不超过 10MB，宽高都不小于 300 像素",
                        }
                    },
                }
            }
        },
    }
}


@router.post(
    "/uploads",
    operation_id="photos_upload",
    summary="上传原图",
    description=(
        "上传一张照片原图（multipart 表单，文件字段名 file）。需要登录。"
        "只接受 JPEG / PNG，不超过 10MB，宽高都不小于 300 像素；文件内容会被校验，"
        "Content-Type 与实际内容不符会被拒绝。上传时提交微信异步内容检测，上传成功后用 file_id 创建照片。"
    ),
    response_model=UploadOut,
    response_description="上传成功，返回文件 ID 和图片尺寸",
    responses=errors_doc(*_AUTH, ErrorCode.UPLOAD_INVALID, ErrorCode.PROVIDER_UNAVAILABLE),
    openapi_extra=_UPLOAD_BODY,
)
async def upload(request: Request, me: Me, db: DB):
    form = await request.form()
    try:
        item = form.get("file")
        if not isinstance(item, UploadFile):
            raise AppError(ErrorCode.UPLOAD_INVALID, "请用表单字段 file 上传图片文件")
        data = await item.read(service.MAX_UPLOAD_BYTES + 1)
        content_type = item.content_type
    finally:
        await form.close()
    # 真实模式由登录依赖提供当前微信小程序会话的 OpenID。
    return await run_in_threadpool(
        service.upload_original,
        db,
        user_id=me.id,
        data=data,
        content_type=content_type,
        open_id=me.wx_mini_open_id,
    )


@router.post(
    "/photos",
    operation_id="photos_create",
    summary="创建照片",
    description=(
        "用已上传的原图创建一张照片（底片）。需要登录。file_id 必须是本人上传、"
        "还没被其他照片使用的原图，否则返回 UPLOAD_NOT_FOUND。抠图处理失败时使用原图。"
        "服务器缺少本地模型时返回 PROVIDER_UNAVAILABLE。"
        "返回拍后快速检测结果，供用户决定是否重拍。图片内容检测通过后可导出，未付费时提供带水印的预览。"
    ),
    response_model=PhotoOut,
    response_description="创建成功，返回照片信息和拍后快速检测结果",
    responses=errors_doc(*_AUTH, ErrorCode.UPLOAD_NOT_FOUND, ErrorCode.PROVIDER_UNAVAILABLE),
)
def create_photo(body: PhotoCreate, me: Me, db: DB):
    return service.create_photo(db, user_id=me.id, body=body, open_id=me.wx_mini_open_id)


@router.get(
    "/photos",
    operation_id="photos_list",
    summary="我的照片列表",
    description="分页列出当前用户未删除的照片，最新的在前。需要登录。列表不含导出图，要看导出图请调用照片详情。",
    response_model=PhotoPage,
    response_description="本页照片和下一页游标",
    responses=errors_doc(*_AUTH),
)
def list_photos(me: Me, db: DB, page: Page):
    return service.list_photos(db, user_id=me.id, page=page)


@router.get(
    "/photos/{photo_id}",
    operation_id="photos_detail",
    summary="照片详情",
    description=(
        "查看一张照片及其全部导出图。需要登录。只能查看自己的照片，否则返回 PHOTO_NOT_FOUND。"
        "内容检测通过后才返回原图链接及导出图。保管期已过（access.active 为 false）时，只返回带水印的预览图。"
    ),
    response_model=PhotoDetail,
    response_description="照片信息和导出图列表",
    responses=errors_doc(*_AUTH, ErrorCode.PHOTO_NOT_FOUND),
)
def photo_detail(photo_id: PhotoId, me: Me, db: DB):
    return service.get_photo_detail(db, user_id=me.id, photo_id=photo_id)


@router.post(
    "/photos/{photo_id}/renders",
    operation_id="photos_render",
    summary="生成导出图",
    description=(
        "按规格、底色、美颜档位生成导出图。需要登录。内容检测通过后才可导出，"
        "等待结果或检测失败返回 PHOTO_NOT_READY，有内容风险或需要复核返回 PHOTO_REJECTED。"
        "没有有效权益（未付费或已过保管期）时生成带水印的预览图（watermarked 为 true）；"
        "权益有效时生成无水印的正式图，但如果权益不允许换规格，且这张照片已有其他规格的无水印图，"
        "返回 SPEC_CHANGE_NOT_ALLOWED。bg_color 必须在规格的可选底色里，beauty_level 不能超过规格的 beauty_max，"
        "不符合时返回 VALIDATION_ERROR。始终自动校正人像光影，可用 blemishes 指定最多 10 个祛痘位置。"
        "位置以成品图左上角为原点，横纵坐标都在 0～1 内。规格、底色、档位、水印和祛痘位置相同时复用已有的图。"
    ),
    response_model=RenderOut,
    response_description="生成（或复用）的导出图",
    responses=errors_doc(
        *_AUTH,
        ErrorCode.PHOTO_NOT_FOUND,
        ErrorCode.SPEC_NOT_FOUND,
        ErrorCode.SPEC_CHANGE_NOT_ALLOWED,
        ErrorCode.PHOTO_NOT_READY,
        ErrorCode.PHOTO_REJECTED,
        ErrorCode.VALIDATION_ERROR,
    ),
)
def create_render(photo_id: PhotoId, body: RenderCreate, me: Me, db: DB):
    return service.render_for_user(db, user_id=me.id, photo_id=photo_id, body=body)


@router.get(
    "/photos/{photo_id}/renders/{render_id}/download",
    operation_id="photos_render_download",
    summary="获取下载链接",
    description=(
        "获取无水印导出图的下载链接，10 分钟内有效。需要登录。"
        "照片须通过内容检测、仍在保管期内，且导出图无水印。带水印的预览图或已过保管期返回 PHOTO_ACCESS_EXPIRED，"
        "前端应引导用户付费或续费。"
    ),
    response_model=DownloadOut,
    response_description="临时下载链接和过期时间",
    responses=errors_doc(
        *_AUTH,
        ErrorCode.PHOTO_NOT_FOUND,
        ErrorCode.PHOTO_ACCESS_EXPIRED,
        ErrorCode.PHOTO_NOT_READY,
        ErrorCode.PHOTO_REJECTED,
    ),
)
def render_download(photo_id: PhotoId, render_id: RenderId, me: Me, db: DB):
    return service.render_download(db, user_id=me.id, photo_id=photo_id, render_id=render_id)


@router.delete(
    "/photos/{photo_id}",
    operation_id="photos_delete",
    summary="删除照片",
    description=(
        "删除照片及其原图、抠图、全部导出图，不可恢复。需要登录。"
        "只能删除自己的照片，否则返回 PHOTO_NOT_FOUND。"
    ),
    response_model=OkResponse,
    response_description="删除成功",
    responses=errors_doc(*_AUTH, ErrorCode.PHOTO_NOT_FOUND),
)
def delete_photo(photo_id: PhotoId, me: Me, db: DB):
    service.delete_photo(db, user_id=me.id, photo_id=photo_id)
    return OkResponse()


def _verify_wechat_message(
    signature: Annotated[str, Query(max_length=40, description="微信消息推送签名", examples=["c" * 40])],
    timestamp: Annotated[
        str, Query(max_length=20, description="微信推送时间戳，单位秒", examples=["1763452800"])
    ],
    nonce: Annotated[str, Query(max_length=128, description="微信签名使用的随机串", examples=["20517"])],
) -> None:
    service.verify_wechat_message(signature=signature, timestamp=timestamp, nonce=nonce)


@callback_router.get(
    "/wechat/media-check",
    operation_id="photos_verify_wechat_callback",
    summary="验证微信消息推送地址",
    description="小程序启用消息推送时由微信调用。无需登录，通过微信签名校验后回传校验串。",
    response_class=PlainTextResponse,
    response_description="微信提供的校验串原文",
    responses=errors_doc(ErrorCode.CALLBACK_SIGNATURE_INVALID, ErrorCode.VALIDATION_ERROR),
    dependencies=[Depends(_verify_wechat_message)],
)
def verify_wechat_callback(
    echostr: Annotated[
        str, Query(max_length=256, description="微信要求原样返回的校验串", examples=["123456789"])
    ],
):
    return echostr


@callback_router.post(
    "/wechat/media-check",
    operation_id="photos_wechat_media_check_callback",
    summary="接收微信内容检测结果",
    description=(
        "微信小程序通过明文 JSON 推送异步图片检测结果。无需登录，必须通过微信签名校验。"
        "依据 trace_id 更新照片内容检测状态，重复通知可以安全重试。"
    ),
    response_class=PlainTextResponse,
    response_description="处理成功，返回纯文本 success",
    responses=errors_doc(
        ErrorCode.CALLBACK_SIGNATURE_INVALID, ErrorCode.VALIDATION_ERROR, ErrorCode.PROVIDER_UNAVAILABLE
    ),
    dependencies=[Depends(_verify_wechat_message)],
)
def wechat_media_check_callback(event: WechatMediaEvent, db: DB):
    service.apply_wechat_media_check(db, event)
    return "success"
