"""照片与文件查询。第一个参数是当前用户 ID，查不到返回 None / 空（service 转成 404）。"""

from collections.abc import Iterable

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import File, Photo, PhotoRender, Spec


def get_photo(db: Session, user_id: int, photo_id: int) -> Photo | None:
    """本人且未删除的照片。"""
    return db.scalar(
        select(Photo).where(Photo.id == photo_id, Photo.user_id == user_id, Photo.status != "purged")
    )


def list_photos(db: Session, user_id: int, *, before_id: int | None, limit: int) -> list[Photo]:
    q = select(Photo).where(Photo.user_id == user_id, Photo.status != "purged")
    if before_id is not None:
        q = q.where(Photo.id < before_id)
    return list(db.scalars(q.order_by(Photo.id.desc()).limit(limit)))


def get_files(db: Session, user_id: int, file_ids: Iterable[int]) -> dict[int, File]:
    ids = list(file_ids)
    if not ids:
        return {}
    rows = db.scalars(select(File).where(File.user_id == user_id, File.id.in_(ids)))
    return {f.id: f for f in rows}


def get_unused_upload(db: Session, user_id: int, file_id: int) -> File | None:
    """本人上传的、有效的、还没被任何照片用作原图的 original 文件。"""
    return db.scalar(
        select(File).where(
            File.id == file_id,
            File.user_id == user_id,
            File.kind == "original",
            File.status == "active",
            ~exists().where(Photo.original_file_id == File.id),
        )
    )


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
) -> PhotoRender | None:
    """同参数（规格、底色、美颜档位、是否水印）已有的导出图，用于复用。"""
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
    if photo.matting_file_id is not None:
        ids.append(photo.matting_file_id)
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


def live_photos_of_user(db: Session, user_id: int) -> list[Photo]:
    return list(db.scalars(select(Photo).where(Photo.user_id == user_id, Photo.status != "purged")))
