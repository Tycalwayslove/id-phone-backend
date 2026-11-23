"""照片与文件查询。第一个参数是当前用户 ID，查不到返回 None / 空（service 转成 404）。"""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.pagination import OffsetPageParams, paginate
from app.models import File, Photo, PhotoRender, Spec


def get_photo(db: Session, user_id: int, photo_id: int, *, lock: bool = False) -> Photo | None:
    """本人已创建且未删除的照片。"""
    stmt = select(Photo).where(
        Photo.id == photo_id, Photo.user_id == user_id, Photo.status.in_(("active", "expired"))
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return db.scalar(stmt)


def _fine_matting_candidates():
    return Photo.matting_level == "fast", Photo.status.in_(("active", "expired"))


def pending_fine_matting_ids(db: Session, older_than: datetime, limit: int) -> list[int]:
    requested_at = Photo.fine_matting_requested_at
    stmt = (
        select(Photo.id)
        .where(*_fine_matting_candidates(), requested_at <= older_than)
        .order_by(requested_at, Photo.id)
        .limit(limit)
    )
    return list(db.scalars(stmt))


def try_lock_fine_matting(db: Session, photo_id: int) -> bool:
    # 负数照片 ID 保留给精细抠图。推理期间只持 advisory lock，照片仍可读取、审核和删除。
    return bool(db.scalar(select(func.pg_try_advisory_xact_lock(-photo_id))))


def get_pending_fine_matting(db: Session, photo_id: int, *, lock: bool = False) -> Photo | None:
    stmt = select(Photo).where(Photo.id == photo_id, *_fine_matting_candidates())
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return db.scalar(stmt)


def list_photos(db: Session, user_id: int, *, before_id: int | None, limit: int) -> list[Photo]:
    q = select(Photo).where(Photo.user_id == user_id, Photo.status.in_(("active", "expired")))
    if before_id is not None:
        q = q.where(Photo.id < before_id)
    return list(db.scalars(q.order_by(Photo.id.desc()).limit(limit)))


def _admin_photos_query(
    *,
    user_id: int | None,
    status: str | None = None,
    matting_level: str | None = None,
    quality_level: str | None = None,
):
    preview = (
        select(File.id.label("file_id"))
        .join(PhotoRender, PhotoRender.file_id == File.id)
        .where(
            PhotoRender.photo_id == Photo.id,
            File.user_id == Photo.user_id,
            File.kind == "preview",
            File.status == "active",
        )
        .order_by(PhotoRender.id.desc())
        .limit(1)
        .correlate(Photo)
        .scalar_subquery()
    )
    stmt = select(Photo, File).outerjoin(
        File,
        (File.id == func.coalesce(preview, Photo.original_file_id))
        & (File.user_id == Photo.user_id)
        & (File.status == "active")
        & (Photo.status != "purged"),
    )
    if user_id is not None:
        stmt = stmt.where(Photo.user_id == user_id)
    if status is not None:
        stmt = stmt.where(Photo.status == status)
    if matting_level is not None:
        stmt = stmt.where(Photo.matting_level == matting_level)
    if quality_level is not None:
        stmt = stmt.where(Photo.quality["level"].astext == quality_level)
    return stmt.order_by(Photo.id.desc())


def list_admin_photos(
    db: Session,
    *,
    page: OffsetPageParams,
    user_id: int | None,
    status: str | None,
    matting_level: str | None,
    quality_level: str | None,
) -> tuple[list[tuple[Photo, File | None]], int]:
    stmt = _admin_photos_query(
        user_id=user_id, status=status, matting_level=matting_level, quality_level=quality_level
    )
    return paginate(db, stmt, page)


def list_recent_admin_photos(db: Session, *, user_id: int, limit: int) -> list[tuple[Photo, File | None]]:
    stmt = _admin_photos_query(user_id=user_id).limit(limit)
    return [(photo, thumbnail) for photo, thumbnail in db.execute(stmt)]


def get_admin_photo(db: Session, photo_id: int) -> Photo | None:
    return db.get(Photo, photo_id)


def list_admin_renders(db: Session, photo: Photo) -> list[tuple[PhotoRender, str, File | None]]:
    stmt = (
        select(PhotoRender, Spec.name, File)
        .join(Spec, Spec.id == PhotoRender.spec_id)
        .outerjoin(File, (File.id == PhotoRender.file_id) & (File.user_id == photo.user_id))
        .where(PhotoRender.photo_id == photo.id)
        .order_by(PhotoRender.id.desc())
    )
    return [(render, name, file) for render, name, file in db.execute(stmt)]


def get_admin_renders_by_ids(
    db: Session, user_id: int, render_ids: set[int]
) -> dict[int, tuple[PhotoRender, str, File | None, str]]:
    if not render_ids:
        return {}
    stmt = (
        select(PhotoRender, Spec.name, File, Photo.status)
        .join(Photo, Photo.id == PhotoRender.photo_id)
        .join(Spec, Spec.id == PhotoRender.spec_id)
        .outerjoin(
            File,
            (File.id == PhotoRender.file_id)
            & (File.user_id == user_id)
            & File.kind.in_(("render", "preview")),
        )
        .where(Photo.user_id == user_id, PhotoRender.id.in_(render_ids))
    )
    return {render.id: (render, name, file, status) for render, name, file, status in db.execute(stmt)}


def get_files(db: Session, user_id: int, file_ids: Iterable[int]) -> dict[int, File]:
    ids = list(file_ids)
    if not ids:
        return {}
    rows = db.scalars(select(File).where(File.user_id == user_id, File.id.in_(ids)))
    return {f.id: f for f in rows}


def get_unused_upload(db: Session, user_id: int, file_id: int) -> File | None:
    """锁定本人上传的有效原图，再检查是否已被正式照片使用。"""
    file = db.scalar(
        select(File)
        .where(File.id == file_id, File.user_id == user_id, File.kind == "original", File.status == "active")
        .with_for_update()
    )
    if file is None:
        return None
    return db.scalar(_unused_originals().where(File.id == file_id, File.user_id == user_id))


def _unused_originals():
    return select(File).where(
        File.kind == "original",
        File.status == "active",
        ~exists().where(
            or_(
                (Photo.original_file_id == File.id) & (Photo.status != "draft"),
                Photo.matting_file_id == File.id,
            )
        ),
    )


def get_upload_draft(db: Session, user_id: int, file_id: int) -> Photo | None:
    return db.scalar(
        select(Photo).where(
            Photo.user_id == user_id, Photo.original_file_id == file_id, Photo.status == "draft"
        )
    )


def lock_photo_for_media_check(db: Session, trace_id: str) -> Photo | None:
    return db.scalar(
        select(Photo)
        .where(Photo.check_result["trace_id"].astext == trace_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def purge_upload_drafts(db: Session, file_ids: list[int]) -> None:
    db.execute(
        update(Photo)
        .where(Photo.original_file_id.in_(file_ids), Photo.status == "draft")
        .values(status="purged")
    )


def lock_orphan_uploads(db: Session, older_than: datetime) -> list[File]:
    candidates = list(
        db.scalars(
            _unused_originals()
            .where(File.created_at < older_than)
            .order_by(File.id)
            .with_for_update(skip_locked=True)
        )
    )
    if not candidates:
        return []
    # 取锁前若有创建照片的事务刚提交，重新检查引用才可安全删除。
    return list(db.scalars(_unused_originals().where(File.id.in_([f.id for f in candidates]))))


def _render_query(user_id: int, photo_id: int):
    return (
        select(PhotoRender, Spec, File)
        .join(Spec, Spec.id == PhotoRender.spec_id)
        .join(File, File.id == PhotoRender.file_id)
        .join(Photo, Photo.id == PhotoRender.photo_id)
        .where(Photo.user_id == user_id, PhotoRender.photo_id == photo_id, File.status == "active")
    )


def list_renders(db: Session, user_id: int, photo_id: int) -> list[tuple[PhotoRender, Spec, File]]:
    rows = db.execute(_render_query(user_id, photo_id).order_by(PhotoRender.id))
    return [(r, s, f) for r, s, f in rows]


def get_render(
    db: Session, user_id: int, photo_id: int, render_id: int
) -> tuple[PhotoRender, Spec, File] | None:
    row = db.execute(_render_query(user_id, photo_id).where(PhotoRender.id == render_id)).first()
    return None if row is None else (row[0], row[1], row[2])


def find_render(
    db: Session,
    user_id: int,
    photo_id: int,
    *,
    spec_id: int,
    bg_color: str,
    beauty_level: int,
    watermarked: bool,
    variant_key: str,
) -> PhotoRender | None:
    """查找规格、底色、美颜档位、祛痘位置和水印均相同的可复用导出图。"""
    return db.scalar(
        select(PhotoRender)
        .join(Photo, Photo.id == PhotoRender.photo_id)
        .join(File, File.id == PhotoRender.file_id)
        .where(
            Photo.user_id == user_id,
            PhotoRender.photo_id == photo_id,
            PhotoRender.spec_id == spec_id,
            PhotoRender.bg_color == bg_color,
            PhotoRender.beauty_level == beauty_level,
            PhotoRender.watermarked == watermarked,
            PhotoRender.variant_key == variant_key,
            File.status == "active",
        )
    )


def has_clean_render_of_other_spec(db: Session, user_id: int, photo_id: int, spec_id: int) -> bool:
    """这张照片是否已有不带水印、规格不同的导出图。"""
    q = select(
        exists()
        .where(
            Photo.user_id == user_id,
            PhotoRender.photo_id == photo_id,
            PhotoRender.photo_id == Photo.id,
            PhotoRender.watermarked.is_(False),
            PhotoRender.spec_id != spec_id,
        )
        .correlate()
    )
    return bool(db.scalar(q))


def active_files_of_photo(db: Session, user_id: int, photo: Photo) -> list[File]:
    """一张照片名下所有未删除的文件：原图、抠图、导出图。"""
    render_file_ids = select(PhotoRender.file_id).where(PhotoRender.photo_id == photo.id)
    ids = [photo.original_file_id]
    ids.extend(
        file_id for file_id in (photo.matting_file_id, photo.previous_matting_file_id) if file_id is not None
    )
    return list(
        db.scalars(
            select(File).where(
                File.user_id == user_id,
                File.status == "active",
                (File.id.in_(ids)) | (File.id.in_(render_file_ids)),
            )
        )
    )


def active_files_of_user(db: Session, user_id: int) -> list[File]:
    return list(db.scalars(select(File).where(File.user_id == user_id, File.status == "active")))


def lock_live_photos_of_user(db: Session, user_id: int) -> list[Photo]:
    stmt = (
        select(Photo)
        .where(Photo.user_id == user_id, Photo.status != "purged")
        .order_by(Photo.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list(db.scalars(stmt))
