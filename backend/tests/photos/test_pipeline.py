from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError

from app.core.config import settings
from app.integrations.matting import MODNET_MODEL, LocalMatting
from app.modules.photos.pipeline.crop import crop_portrait
from app.modules.photos.pipeline.face import YUNET_MODEL, Face, detect_faces
from app.modules.photos.pipeline.lighting import cheek_samples, luminance, white_balance_gains
from app.modules.photos.pipeline.quality import assess_quality
from app.modules.photos.pipeline.retouch import retouch
from app.modules.photos.schemas import RenderCreate
from tests.photos.helpers import jpeg_bytes

FACE = Face(120, 116, 160, 194, ((163, 173), (237, 173), (200, 215), (172, 250), (228, 250)), 0.95)


def test_face_crop_targets_head_height_and_headroom():
    original = Image.new("RGBA", (400, 500))
    ImageDraw.Draw(original).ellipse((110, 65, 290, 310), fill=(185, 135, 113, 255))

    cropped, face = crop_portrait(original, (350, 450), FACE)
    alpha = np.asarray(cropped.getchannel("A"))
    top = np.flatnonzero((alpha > 127).any(axis=1))[0]
    chin = face.y + face.height
    assert (chin - top) / cropped.height == pytest.approx(0.62, abs=0.02)
    assert top / cropped.height == pytest.approx(0.08, abs=0.02)
    assert face.center_x == pytest.approx(cropped.width / 2)
    assert face.width / face.height == pytest.approx(FACE.width / FACE.height)


@pytest.mark.parametrize(("height", "offset"), [(400, 0), (500, -55), (500, 55)])
def test_face_crop_compensates_for_bottom_or_side_bounds(height, offset):
    original = Image.new("RGBA", (400, height))
    ImageDraw.Draw(original).rectangle((125 + offset, 65, 275 + offset, 310), fill=(185, 135, 113, 255))
    face = replace(FACE, x=FACE.x + offset, landmarks=tuple((x + offset, y) for x, y in FACE.landmarks))

    cropped, fitted = crop_portrait(original, (350, 450), face)
    scale = fitted.height / face.height
    left = face.x - fitted.x / scale
    top = face.y - fitted.y / scale
    assert 0.62 < 245 * scale / cropped.height <= 0.70
    assert fitted.center_x == pytest.approx(cropped.width / 2)
    assert left >= -1e-6
    assert left + cropped.width / scale <= original.width + 1e-6
    assert top + cropped.height / scale <= original.height + 1e-6


def test_face_crop_fades_unavoidable_bottom_padding_from_body_rows():
    original = Image.new("RGBA", (400, 350))
    draw = ImageDraw.Draw(original)
    draw.rectangle((80, 300, 319, 349), fill=(80, 120, 160, 204))
    draw.rectangle((125, 65, 275, 310), fill=(185, 135, 113, 255))

    cropped, face = crop_portrait(original, (350, 450), FACE)
    scale = face.height / FACE.height
    source_bottom = face.y + (original.height - FACE.y) * scale
    seam = round(source_bottom)
    pixels = np.asarray(cropped)
    alpha = pixels[seam - 1 :, cropped.width // 2, 3].astype(int)
    assert 245 * scale / cropped.height == pytest.approx(0.70)
    assert alpha[0] == 204 and alpha[1] >= 200 and alpha[-1] == 0
    assert (np.diff(alpha) <= 0).all() and max(-np.diff(alpha)) < 10
    assert pixels[seam + 10, cropped.width // 2, :3] == pytest.approx((80, 120, 160), abs=2)
    assert not pixels[seam:, 0, 3].any()


def test_face_crop_keeps_transparent_padding_outside_original():
    original = Image.new("RGB", (400, 500), "red")
    face = Face(0, 10, 160, 194, ((43, 67), (117, 67), (80, 109), (52, 144), (108, 144)), 0.95)
    cropped, fitted = crop_portrait(original, (350, 450), face)
    assert cropped.getpixel((0, 0))[3] == 0
    assert cropped.getpixel((175, 225)) == (255, 0, 0, 255)
    assert fitted.center_x == pytest.approx(175)


def test_no_face_crops_center_without_padding():
    original = Image.new("RGB", (500, 400), "red")
    ImageDraw.Draw(original).rectangle((100, 0, 399, 400), fill="green")
    cropped, face = crop_portrait(original, (300, 400), None)
    assert cropped.getextrema() == ((0, 0), (128, 128), (0, 0))
    assert face is None


def test_beauty_protects_features_and_preserves_alpha():
    y, x = np.indices((400, 400))
    rgb = np.empty((400, 400, 4), dtype=np.uint8)
    rgb[:, :, :3] = np.array([185, 135, 113]) + (8 * ((x + y) % 2))[:, :, None]
    rgb[:, :, 3] = 255
    rgb[:40, :, 3] = 0
    image = Image.fromarray(rgb)

    auto = np.asarray(retouch(image, FACE))
    light = np.asarray(retouch(image, FACE, beauty_level=2))
    strong = np.asarray(retouch(image, FACE, beauty_level=5))

    for x, y in FACE.landmarks:
        region = (slice(y - 3, y + 4), slice(x - 3, x + 4))
        np.testing.assert_array_equal(strong[region], auto[region])
    np.testing.assert_array_equal(strong[:, :, 3], rgb[:, :, 3])
    cheek = (slice(206, 225), slice(136, 160), 1)
    assert auto[cheek].mean() < light[cheek].mean() < strong[cheek].mean()
    assert auto[cheek].std() > light[cheek].std() > strong[cheek].std()
    np.testing.assert_array_equal(strong[:, :25], auto[:, :25])


def test_auto_light_reduces_left_right_difference_at_level_zero():
    image = Image.new("RGB", (400, 420), (155, 155, 155))
    ImageDraw.Draw(image).rectangle((0, 0, 199, 419), fill=(84, 84, 84))
    before = abs(luminance(cheek_samples(image, FACE)[0]) - luminance(cheek_samples(image, FACE)[1]))
    left, right = cheek_samples(retouch(image, FACE), FACE)
    after = abs(luminance(left) - luminance(right))
    assert before / 2 <= after < before


def test_white_balance_samples_only_foreground_midtones():
    rgb = np.empty((120, 120, 3), dtype=np.uint8)
    rgb[:30] = (210, 60, 35)  # 蒙版外的中间调
    rgb[30:60] = (255, 244, 231)  # 过曝
    rgb[60:90] = (50, 10, 5)  # 过暗
    rgb[90:] = (140, 140, 140)
    alpha = np.full((120, 120), 255, dtype=np.uint8)
    alpha[:30] = 127
    alpha[90:] = 128
    np.testing.assert_array_equal(white_balance_gains(rgb, alpha, None), [1, 1, 1])

    rgb[90:] = (45, 100, 245)
    gains = white_balance_gains(rgb, alpha, None)
    assert gains[0] == pytest.approx(1.1)
    assert 0.9 <= gains[2] < 1.0
    np.testing.assert_array_equal(white_balance_gains(rgb, None, None), [1, 1, 1])


def test_auto_white_balance_limits_loss_of_warm_face_tones():
    original = Image.new("RGBA", (400, 420), (224, 148, 95, 255))
    rgb = np.asarray(original.convert("RGB"))
    alpha = np.asarray(original.getchannel("A"))
    unprotected_gains = white_balance_gains(rgb, alpha, None)
    protected = retouch(original, FACE)

    samples = np.array(
        [
            rgb[210, 200] / 255,
            rgb[210, 200] / 255 * unprotected_gains,
            np.asarray(protected)[210, 200, :3] / 255,
        ],
        dtype=np.float32,
    )
    before, unprotected, after = cv2.cvtColor(samples[:, None], cv2.COLOR_RGB2LAB)[:, 0, 2]
    assert before - unprotected > 2.5
    assert 0 < before - after <= 2.5  # 转回 8 位 RGB 时有舍入误差


def test_blemish_inpaint_only_changes_the_selected_circle():
    image = Image.new("RGB", (400, 400), (180, 140, 120))
    ImageDraw.Draw(image).point((149, 230), fill=(30, 30, 30))
    ImageDraw.Draw(image).point((155, 230), fill=(40, 40, 40))
    baseline = np.asarray(retouch(image, FACE))
    edited = np.asarray(retouch(image, FACE, blemishes=[(149 / 399, 230 / 399)]))
    assert edited[230, 149, 0] > baseline[230, 149, 0] + 70
    y, x = np.ogrid[:400, :400]
    outside = (x - 149) ** 2 + (y - 230) ** 2 > 2**2
    np.testing.assert_array_equal(edited[outside], baseline[outside])


@pytest.mark.parametrize(
    ("faces", "light", "level", "codes"),
    [
        ([], (150, 150), "fail", {"no_face"}),
        ([FACE, FACE], (150, 150), "fail", {"multiple_faces"}),
        ([replace(FACE, height=90, width=65)], (150, 150), "warn", {"face_too_small"}),
        ([replace(FACE, y=20)], (150, 150), "warn", {"face_off_center"}),
        ([FACE], (60, 60), "warn", {"too_dark"}),
        ([FACE], (235, 235), "warn", {"too_bright"}),
        (
            [replace(FACE, landmarks=(*FACE.landmarks[:2], (225, 215), *FACE.landmarks[3:]))],
            (150, 150),
            "warn",
            {"not_frontal"},
        ),
        ([FACE], (105, 172), "warn", {"uneven_light"}),
        ([FACE], (155, 155), "ok", set()),
    ],
)
def test_quality_detects_each_issue(faces, light, level, codes):
    left, right = light
    image = Image.new("RGB", (400, 500), (right,) * 3)
    ImageDraw.Draw(image).rectangle((0, 0, 199, 499), fill=(left,) * 3)
    result = assess_quality(image, faces)
    assert result.level == level
    assert {issue.code for issue in result.issues} == codes
    assert all("请" in issue.message for issue in result.issues)


@pytest.mark.parametrize(
    "blemishes",
    [
        [{"x": -0.01, "y": 0}],
        [{"x": 1, "y": 1.01}],
        [{"x": float("nan"), "y": 1}],
        [{"x": 1, "y": float("inf")}],
        [{"x": 1}],
        [{"x": "0.4", "y": 1}],
        [{"x": 0, "y": 1}] * 11,
        None,
    ],
)
def test_blemish_validation_rejects_invalid_points(blemishes):
    with pytest.raises(ValidationError):
        RenderCreate(spec_code="test", blemishes=blemishes)


def test_blemish_validation_accepts_edges_and_optional_list():
    assert RenderCreate(spec_code="test").blemishes == []
    body = RenderCreate(spec_code="test", blemishes=[{"x": 0, "y": 1}] * 10)
    assert [(point.x, point.y) for point in body.blemishes] == [(0.0, 1.0)] * 10


def test_missing_models_explain_how_to_install(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "photo_models_dir", tmp_path)
    with pytest.raises(FileNotFoundError, match=r"modnet.*scripts\.download_models"):
        LocalMatting().matte(jpeg_bytes())
    with pytest.raises(FileNotFoundError, match=r"yunet.*scripts\.download_models"):
        detect_faces(Image.new("RGB", (300, 300)))


def test_yunet_remaps_large_input_and_filters_confidence(monkeypatch, tmp_path):
    from app.modules.photos.pipeline import face as face_module

    (tmp_path / YUNET_MODEL).touch()
    monkeypatch.setattr(settings, "photo_models_dir", tmp_path)
    row = [100, 120, 180, 200, 140, 180, 220, 180, 180, 210, 155, 250, 205, 250, 0.95]
    rows = np.asarray([row, [*row[:-1], 0.25]], dtype=np.float32)
    detector = SimpleNamespace(setInputSize=Mock(), detect=Mock(return_value=(1, rows)))
    monkeypatch.setattr(face_module, "_detector", detector)
    monkeypatch.setattr(face_module, "_model_path", tmp_path / YUNET_MODEL)

    found = detect_faces(Image.new("RGB", (1920, 1440)))
    detector.setInputSize.assert_called_once_with((960, 720))
    assert len(found) == 1
    assert found[0].x == 200 and found[0].height == 400
    assert found[0].landmarks[2] == (360, 420)
    assert found[0].confidence == pytest.approx(0.95)


def test_local_modnet_returns_original_size_and_uses_one_session():
    if not (settings.photo_models_dir / MODNET_MODEL).is_file():
        pytest.skip("本机缺少 MODNet 模型")
    from app.integrations.matting import _get_modnet_session

    data = LocalMatting().matte(jpeg_bytes())
    with Image.open(BytesIO(data)) as result:
        assert (result.format, result.mode, result.size) == ("PNG", "RGBA", (600, 800))
        assert result.getchannel("A").getextrema()[0] < 255
    assert _get_modnet_session() is _get_modnet_session()


def test_local_yunet_runs_without_a_real_face():
    if not (settings.photo_models_dir / YUNET_MODEL).is_file():
        pytest.skip("本机缺少 YuNet 模型")
    assert detect_faces(Image.new("RGB", (360, 480), "gray")) == []
