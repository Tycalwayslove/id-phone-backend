"""照片与文件业务。

- 对外入口（upload_original、create_photo、render_for_user、delete_photo ……）内部 commit。
- 跨模块函数（save_file、get_photo_for_user、render、purge_all_for_user）只 flush，由调用方 commit。
"""

import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.pagination import PageParams
from app.core.utils import utcnow
from app.integrations import wechat
from app.integrations.matting import get_matting
from app.integrations.storage import build_key, get_storage
from app.models import File, Photo, PhotoRender, Spec
from app.modules.photos import imaging, repo
from app.modules.photos.schemas import (
    AccessOut,
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
from app.modules.specs import service as spec_service

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
DOWNLOAD_URL_SECONDS = 600
MEDIA_CHECK_URL_SECONDS = 30 * 60
# 没有绑定照片的上传文件放在这个目录下（文件 ID 还没有照片 ID 可用）
UPLOAD_OWNER = "uploads"
log = logging.getLogger(__name__)


# ---------- 跨模块函数（见 modules/CONTRACTS.md） ----------


def save_file(
    db: Session,
    *,
    user_id: int,
    kind: str,
    data: bytes,
    mime: str,
    ext: str,
    owner: str,
    spec_code: str | None = None,
    bg: str | None = None,
    beauty: int | None = None,
) -> File:
    """存到对象存储并登记 files 表。key 里要带文件 ID，所以先占位插入拿到 ID，再写存储、回填 key。"""
    storage = get_storage()
    f = File(
        user_id=user_id,
        kind=kind,
        bucket=storage.bucket,
        storage_key=f"pending/{uuid.uuid4().hex}",
        mime=mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        status="active",
    )
    db.add(f)
    db.flush()
    key = build_key(
        user_id=user_id,
        owner=owner,
        kind=kind,
        file_id=f.id,
        ext=ext,
        spec_code=spec_code,
        bg=bg,
        beauty=beauty,
    )
    storage.put(key, data, mime)
    f.storage_key = key
    db.flush()
    return f


def file_url(file: File, expires_in: int = DOWNLOAD_URL_SECONDS) -> str:
    """签名下载链接。"""
    return get_storage().url(file.storage_key, expires_in)


def get_photo_for_user(db: Session, user_id: int, photo_id: int) -> Photo:
    """本人的、已创建且未删除的照片；否则 PHOTO_NOT_FOUND。"""
    photo = repo.get_photo(db, user_id, photo_id)
    if photo is None:
        raise AppError(ErrorCode.PHOTO_NOT_FOUND)
    return photo


def _check_status(photo: Photo) -> str:
    if photo.check_result is None:
        # 兼容启用审核前创建的照片。真实模式要求取得审核结果。
        return "passed" if settings.wechat_mode == "fake" else "failed"
    return photo.check_result.get("status", "failed")


def _require_passed_check(photo: Photo) -> None:
    match _check_status(photo):
        case "passed":
            return
        case "rejected":
            raise AppError(ErrorCode.PHOTO_REJECTED)
        case "pending":
            raise AppError(ErrorCode.PHOTO_NOT_READY)
        case _:
            raise AppError(ErrorCode.PHOTO_NOT_READY, "照片内容检测结果不可用，请重新上传")


def render(
    db: Session,
    *,
    user_id: int,
    photo_id: int,
    spec: Spec,
    bg_color: str,
    beauty_level: int,
    watermarked: bool,
) -> PhotoRender:
    """生成导出图；同参数已有就直接复用。不 commit。"""
    photo = get_photo_for_user(db, user_id, photo_id)
    _require_passed_check(photo)
    existing = repo.find_render(
        db,
        user_id,
        photo.id,
        spec_id=spec.id,
        bg_color=bg_color,
        beauty_level=beauty_level,
        watermarked=watermarked,
    )
    if existing is not None:
        return existing

    # 底片：有抠图用抠图，否则用原图
    base_id = photo.matting_file_id or photo.original_file_id
    base = repo.get_files(db, user_id, [base_id]).get(base_id)
    if base is None or base.status != "active":
        raise AppError(ErrorCode.PHOTO_NOT_READY)
    out = imaging.make_render(
        get_storage().get(base.storage_key),
        width_px=spec.width_px,
        height_px=spec.height_px,
        bg_color=bg_color,
        dpi=spec.dpi,
        max_kb=spec.file_size_max_kb,
        watermarked=watermarked,
        beauty_level=beauty_level,
    )
    f = save_file(
        db,
        user_id=user_id,
        kind="preview" if watermarked else "render",
        data=out,
        mime="image/jpeg",
        ext="jpg",
        owner=f"p{photo.id}",
        spec_code=spec.code,
        bg=bg_color,
        beauty=beauty_level,
    )
    row = PhotoRender(
        photo_id=photo.id,
        spec_id=spec.id,
        file_id=f.id,
        bg_color=bg_color,
        beauty_level=beauty_level,
        watermarked=watermarked,
    )
    try:
        with db.begin_nested():
            db.add(row)
    except IntegrityError:
        # 并发请求抢先生成了同参数的导出图：用对方的
        again = repo.find_render(
            db,
            user_id,
            photo.id,
            spec_id=spec.id,
            bg_color=bg_color,
            beauty_level=beauty_level,
            watermarked=watermarked,
        )
        if again is None:
            raise
        return again
    return row


def _purge_files(db: Session, files: list[File]) -> None:
    """删除存储里的文件并标记 purged。存储里本来就没有的不报错。"""
    storage = get_storage()
    now = utcnow()
    for f in files:
        storage.delete(f.storage_key)
        f.status = "purged"
        f.purged_at = now
    db.flush()


def purge_orphan_uploads(db: Session, older_than: datetime) -> int:
    """清理指定时间之前、未被照片引用的原图，返回清理数量。不 commit。"""
    files = repo.lock_orphan_uploads(db, older_than)
    if files:
        _purge_files(db, files)
        repo.purge_upload_drafts(db, [f.id for f in files])
    return len(files)


def purge_all_for_user(db: Session, user_id: int) -> int:
    """注销账号用：删除该用户全部存储文件，files 和 photos 标记 purged。返回删除的文件数。不 commit。"""
    files = repo.active_files_of_user(db, user_id)
    _purge_files(db, files)
    for p in repo.live_photos_of_user(db, user_id):
        p.status = "purged"
    db.flush()
    return len(files)


# ---------- 接口用的入口 ----------


def _access_out(db: Session, user_id: int, photo_id: int) -> AccessOut:
    from app.modules.entitlements import service as ent_service

    a = ent_service.photo_access(db, user_id, photo_id)
    return AccessOut.model_validate(a)


def _photo_out(photo: Photo, original: File, access: AccessOut) -> PhotoOut:
    return PhotoOut(
        id=photo.id,
        source=photo.source,
        status=photo.status,
        created_at=photo.created_at,
        original_url=file_url(original) if _check_status(photo) == "passed" else "",
        access=access,
    )


def _render_out(render_row: PhotoRender, spec: Spec, file: File) -> RenderOut:
    return RenderOut(
        id=render_row.id,
        spec_code=spec.code,
        spec_name=spec.name,
        bg_color=render_row.bg_color,
        beauty_level=render_row.beauty_level,
        watermarked=render_row.watermarked,
        width_px=spec.width_px,
        height_px=spec.height_px,
        size_bytes=file.size_bytes,
        preview_url=file_url(file),
    )


def _submit_media_check(original: File, open_id: str | None) -> dict[str, str]:
    if settings.wechat_mode == "real":
        if not settings.wx_msg_token:
            raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "照片内容检测暂时不可用，请稍后重试")
        if not open_id:
            raise AppError(ErrorCode.AUTH_INVALID, "请重新登录微信小程序后再上传照片")
    try:
        trace_id = wechat.media_check_async(
            media_url=file_url(original, MEDIA_CHECK_URL_SECONDS), open_id=open_id
        )
    except wechat.DeliveryError:
        raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "照片内容检测暂时不可用，请稍后重试") from None
    if trace_id is None:
        return {"status": "passed"}
    return {"status": "pending", "trace_id": trace_id}


def upload_original(
    db: Session, *, user_id: int, data: bytes, content_type: str | None, open_id: str | None = None
) -> UploadOut:
    """校验并保存原图，用草稿承接异步内容检测。"""
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise AppError(ErrorCode.UPLOAD_INVALID, "图片不能为空，且不能超过 10MB")
    try:
        fmt, width, height = imaging.inspect_image(data)
    except imaging.ImageInvalidError as e:
        raise AppError(ErrorCode.UPLOAD_INVALID, str(e)) from e
    mime, ext = imaging.ALLOWED_FORMATS[fmt]
    if content_type != mime:
        raise AppError(ErrorCode.UPLOAD_INVALID, "文件类型与内容不一致，只支持 JPEG 或 PNG")
    storage_key = None
    try:
        with db.begin_nested():
            f = save_file(
                db, user_id=user_id, kind="original", data=data, mime=mime, ext=ext, owner=UPLOAD_OWNER
            )
            storage_key = f.storage_key
            check_result = _submit_media_check(f, open_id)
            db.add(
                Photo(
                    user_id=user_id,
                    source="upload",
                    original_file_id=f.id,
                    status="draft",
                    check_result=check_result,
                )
            )
    except Exception:
        if storage_key is not None:
            try:
                get_storage().delete(storage_key)
            except OSError:
                log.warning("清理未完成上传的原图失败")
        raise
    db.commit()
    return UploadOut(file_id=f.id, width=width, height=height)


def _attach_matting(db: Session, photo: Photo, original: File) -> None:
    try:
        data = get_matting().matte(get_storage().get(original.storage_key))
    except TimeoutError:
        log.warning("抠图超时，使用原图")
        return
    except Exception:
        log.warning("抠图失败，使用原图")
        return
    try:
        with db.begin_nested():
            matting = save_file(
                db,
                user_id=photo.user_id,
                kind="matting",
                data=data,
                mime="image/png",
                ext="png",
                owner=f"p{photo.id}",
            )
            photo.matting_file_id = matting.id
    except OSError:
        log.warning("抠图文件保存失败，使用原图")


def create_photo(db: Session, *, user_id: int, body: PhotoCreate, open_id: str | None = None) -> PhotoOut:
    original = repo.get_unused_upload(db, user_id, body.file_id)
    if original is None:
        raise AppError(ErrorCode.UPLOAD_NOT_FOUND)
    photo = repo.get_upload_draft(db, user_id, original.id)
    if photo is None:
        # 发布前上传但尚未绑定照片的原图，仍可以创建并补交审核。
        photo = Photo(
            user_id=user_id,
            source=body.source,
            original_file_id=original.id,
            check_result=_submit_media_check(original, open_id),
        )
        db.add(photo)
        db.flush()
    _attach_matting(db, photo, original)
    photo.source = body.source
    photo.status = "active"
    db.flush()
    db.refresh(photo)
    out = _photo_out(photo, original, _access_out(db, user_id, photo.id))
    db.commit()
    return out


def verify_wechat_message(*, signature: str, timestamp: str, nonce: str) -> None:
    token = settings.wx_msg_token
    if not token:
        raise AppError(ErrorCode.CALLBACK_SIGNATURE_INVALID)
    signed = "".join(sorted((token, timestamp, nonce))).encode()
    expected = hashlib.sha1(signed).hexdigest()
    if not hmac.compare_digest(expected.encode(), signature.encode()):
        raise AppError(ErrorCode.CALLBACK_SIGNATURE_INVALID)


def apply_wechat_media_check(db: Session, event: WechatMediaEvent) -> None:
    if event.message_type.lower() != "event" or event.event != "wxa_media_check":
        return
    if event.app_id != settings.wx_mini_app_id or not event.trace_id:
        raise AppError(ErrorCode.VALIDATION_ERROR, "微信内容检测事件缺少有效的小程序 AppID 或任务 ID")
    photo = repo.lock_photo_for_media_check(db, event.trace_id)
    if photo is None:
        # 微信可能在上传事务提交前推送结果，返回失败让微信重试。
        raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, "照片内容检测任务暂不可用")
    if photo.status != "purged" and _check_status(photo) == "pending":
        suggestion = event.result.suggest if event.errcode == 0 and event.result else None
        status = {"pass": "passed", "risky": "rejected", "review": "rejected"}.get(suggestion, "failed")
        photo.check_result = {"status": status, "trace_id": event.trace_id}
    db.commit()


def list_photos(db: Session, *, user_id: int, page: PageParams) -> PhotoPage:
    from app.modules.entitlements import service as ent_service

    rows = repo.list_photos(db, user_id, before_id=page.before_id(), limit=page.fetch_limit)
    rows, next_cursor = page.slice(rows)
    files = repo.get_files(db, user_id, [p.original_file_id for p in rows])
    access = ent_service.photo_access_many(db, user_id, [p.id for p in rows])
    items = [_photo_out(p, files[p.original_file_id], AccessOut.model_validate(access[p.id])) for p in rows]
    return PhotoPage(items=items, next_cursor=next_cursor)


def get_photo_detail(db: Session, *, user_id: int, photo_id: int) -> PhotoDetail:
    photo = get_photo_for_user(db, user_id, photo_id)
    original = repo.get_files(db, user_id, [photo.original_file_id])[photo.original_file_id]
    base = _photo_out(photo, original, _access_out(db, user_id, photo.id))
    if _check_status(photo) != "passed":
        return PhotoDetail(**base.model_dump(), renders=[])
    renders = repo.list_renders(db, user_id, photo.id)
    # 保管期外不再展示无水印的正式图，避免泄露可直接使用的链接
    if not base.access.active:
        renders = [r for r in renders if r[0].watermarked]
    return PhotoDetail(**base.model_dump(), renders=[_render_out(*r) for r in renders])


def render_for_user(db: Session, *, user_id: int, photo_id: int, body: RenderCreate) -> RenderOut:
    photo = get_photo_for_user(db, user_id, photo_id)
    _require_passed_check(photo)
    spec = spec_service.get_active_spec(db, body.spec_code)

    colors = spec.bg_colors or ["#FFFFFF"]
    if body.bg_color is None:
        bg = colors[0]
    else:
        bg = next((c for c in colors if c.upper() == body.bg_color.upper()), None)
        if bg is None:
            raise AppError(ErrorCode.VALIDATION_ERROR, "底色不在该规格支持的范围内")
    if body.beauty_level > spec.beauty_max:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"该规格美颜档位最高为 {spec.beauty_max}")

    access = _access_out(db, user_id, photo.id)
    watermarked = not access.active
    if (
        access.active
        and not access.spec_change
        and repo.has_clean_render_of_other_spec(db, user_id, photo.id, spec.id)
    ):
        raise AppError(ErrorCode.SPEC_CHANGE_NOT_ALLOWED)

    row = render(
        db,
        user_id=user_id,
        photo_id=photo.id,
        spec=spec,
        bg_color=bg,
        beauty_level=body.beauty_level,
        watermarked=watermarked,
    )
    found = repo.get_render(db, user_id, photo.id, row.id)
    assert found is not None
    out = _render_out(*found)
    db.commit()
    return out


def render_download(db: Session, *, user_id: int, photo_id: int, render_id: int) -> DownloadOut:
    photo = get_photo_for_user(db, user_id, photo_id)
    _require_passed_check(photo)
    found = repo.get_render(db, user_id, photo.id, render_id)
    if found is None:
        raise AppError(ErrorCode.PHOTO_NOT_FOUND)
    row, _spec, file = found
    if row.watermarked or not _access_out(db, user_id, photo.id).active:
        raise AppError(ErrorCode.PHOTO_ACCESS_EXPIRED)
    return DownloadOut(
        url=file_url(file, DOWNLOAD_URL_SECONDS),
        expires_at=utcnow() + timedelta(seconds=DOWNLOAD_URL_SECONDS),
    )


def delete_photo(db: Session, *, user_id: int, photo_id: int) -> None:
    photo = get_photo_for_user(db, user_id, photo_id)
    _purge_files(db, repo.active_files_of_photo(db, user_id, photo))
    photo.status = "purged"
    db.commit()
