"""照片与文件业务。

- 对外入口（upload_original、create_photo、render_for_user、delete_photo ……）内部 commit。
- 跨模块函数（save_file、get_photo_for_user、render、purge_all_for_user）只 flush，由调用方 commit。
"""

import hashlib
import uuid
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import PageParams
from app.core.errors import AppError, ErrorCode
from app.core.utils import decode_cursor, encode_cursor, utcnow
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
)
from app.modules.specs import service as spec_service

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
DOWNLOAD_URL_SECONDS = 600
# 没有绑定照片的上传文件放在这个目录下（文件 ID 还没有照片 ID 可用）
UPLOAD_OWNER = "uploads"


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
    """本人的、未删除的照片；否则 PHOTO_NOT_FOUND。"""
    photo = repo.get_photo(db, user_id, photo_id)
    if photo is None:
        raise AppError(ErrorCode.PHOTO_NOT_FOUND)
    return photo


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
    return AccessOut(active=a.active, access_until=a.access_until, spec_change=a.spec_change)


def _photo_out(db: Session, user_id: int, photo: Photo, original: File | None = None) -> PhotoOut:
    if original is None:
        original = repo.get_files(db, user_id, [photo.original_file_id])[photo.original_file_id]
    return PhotoOut(
        id=photo.id,
        source=photo.source,
        status=photo.status,
        created_at=photo.created_at,
        original_url=file_url(original),
        access=_access_out(db, user_id, photo.id),
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


def upload_original(db: Session, *, user_id: int, data: bytes, content_type: str | None) -> UploadOut:
    """校验并保存上传的原图。"""
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise AppError(ErrorCode.UPLOAD_INVALID, "图片不能为空，且不能超过 10MB")
    try:
        fmt, width, height = imaging.inspect_image(data)
    except imaging.ImageInvalidError as e:
        raise AppError(ErrorCode.UPLOAD_INVALID, str(e)) from e
    mime, ext = imaging.ALLOWED_FORMATS[fmt]
    if content_type != mime:
        raise AppError(ErrorCode.UPLOAD_INVALID, "文件类型与内容不一致，只支持 JPEG 或 PNG")
    f = save_file(db, user_id=user_id, kind="original", data=data, mime=mime, ext=ext, owner=UPLOAD_OWNER)
    db.commit()
    return UploadOut(file_id=f.id, width=width, height=height)


def create_photo(db: Session, *, user_id: int, body: PhotoCreate) -> PhotoOut:
    original = repo.get_unused_upload(db, user_id, body.file_id)
    if original is None:
        raise AppError(ErrorCode.UPLOAD_NOT_FOUND)
    if settings.matting_mode != "fake":
        # TODO: 接入抠图服务后在这里生成 matting 文件
        raise NotImplementedError(f"抠图模式 {settings.matting_mode} 尚未接入")
    photo = Photo(
        user_id=user_id,
        source=body.source,
        original_file_id=original.id,
        matting_file_id=None,
        status="active",
    )
    try:
        with db.begin_nested():
            db.add(photo)
    except IntegrityError as e:
        # 并发创建：同一个文件已被另一张照片占用
        raise AppError(ErrorCode.UPLOAD_NOT_FOUND) from e
    db.refresh(photo)  # 取回数据库默认值（created_at）
    out = _photo_out(db, user_id, photo, original)
    db.commit()
    return out


def list_photos(db: Session, *, user_id: int, page: PageParams) -> PhotoPage:
    cur = decode_cursor(page.cursor)
    before = cur.get("id") if cur and isinstance(cur.get("id"), int) else None
    rows = repo.list_photos(db, user_id, before_id=before, limit=page.limit + 1)
    has_more = len(rows) > page.limit
    rows = rows[: page.limit]
    files = repo.get_files(db, user_id, [p.original_file_id for p in rows])
    items = [_photo_out(db, user_id, p, files[p.original_file_id]) for p in rows]
    return PhotoPage(items=items, next_cursor=encode_cursor({"id": rows[-1].id}) if has_more else None)


def get_photo_detail(db: Session, *, user_id: int, photo_id: int) -> PhotoDetail:
    photo = get_photo_for_user(db, user_id, photo_id)
    base = _photo_out(db, user_id, photo)
    renders = repo.list_renders(db, user_id, photo.id)
    # 保管期外不再展示无水印的正式图，避免泄露可直接使用的链接
    if not base.access.active:
        renders = [r for r in renders if r[0].watermarked]
    return PhotoDetail(**base.model_dump(), renders=[_render_out(*r) for r in renders])


def render_for_user(db: Session, *, user_id: int, photo_id: int, body: RenderCreate) -> RenderOut:
    photo = get_photo_for_user(db, user_id, photo_id)
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
