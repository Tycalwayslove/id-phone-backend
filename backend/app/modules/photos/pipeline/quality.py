"""从未经精修的原图给出拍后提示。"""

from collections.abc import Sequence
from math import hypot

from PIL import Image

from app.modules.photos.pipeline.face import Face
from app.modules.photos.pipeline.lighting import cheek_samples, luminance
from app.modules.photos.schemas import PhotoQuality, QualityCode, QualityIssue

MESSAGES: dict[QualityCode, str] = {
    "no_face": "没有检测到人脸，请把脸放进轮廓框再拍",
    "multiple_faces": "照片里有多张人脸，请让其他人离开画面再拍",
    "face_too_small": "脸有点小，请靠近一点再拍",
    "face_off_center": "脸有点偏，请把脸移到轮廓框中间再拍",
    "too_dark": "脸有点暗，请面朝光线再拍",
    "too_bright": "脸有点亮，请避开直射光再拍",
    "not_frontal": "请把头摆正，正对镜头再拍",
    "uneven_light": "两边脸的亮度差有点大，请面朝均匀的光线再拍",
}


def _issue(code: QualityCode) -> QualityIssue:
    return QualityIssue(code=code, message=MESSAGES[code])


def _not_frontal(face: Face) -> bool:
    (rx, ry), (lx, ly), (nx, ny), *_ = face.landmarks
    dx, dy = lx - rx, ly - ry
    eye_distance = hypot(dx, dy)
    if not eye_distance:
        return True
    # 鼻尖在眼轴上的投影相对中点的偏移，避免低头或仰头单独影响左右对称性。
    nose_offset = abs((nx - (rx + lx) / 2) * dx + (ny - (ry + ly) / 2) * dy) / eye_distance**2
    return nose_offset > 0.20 or abs(dy) / eye_distance > 0.22


def assess_quality(image: Image.Image, faces: Sequence[Face]) -> PhotoQuality:
    if not faces:
        return PhotoQuality(level="fail", issues=[_issue("no_face")])
    if len(faces) > 1:
        return PhotoQuality(level="fail", issues=[_issue("multiple_faces")])

    face = faces[0]
    issues = []
    if face.height / image.height < 0.24 or face.width / image.width < 0.18:
        issues.append(_issue("face_too_small"))
    if abs(face.center_x / image.width - 0.5) > 0.19 or not 0.23 <= face.y / image.height <= 0.63:
        issues.append(_issue("face_off_center"))
    if _not_frontal(face):
        issues.append(_issue("not_frontal"))

    left, right = cheek_samples(image, face)
    if left.size and right.size:
        left_y, right_y = luminance(left), luminance(right)
        mean_y = (left_y + right_y) / 2
        if mean_y < 80:
            issues.append(_issue("too_dark"))
        elif mean_y > 220:
            issues.append(_issue("too_bright"))
        if abs(left_y - right_y) > 42:
            issues.append(_issue("uneven_light"))
    return PhotoQuality(level="warn" if issues else "ok", issues=issues)
