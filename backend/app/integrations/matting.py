"""抠图适配器，统一返回带透明通道的 PNG。"""

import io
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Protocol

import httpx
import numpy as np
from PIL import Image, ImageChops, ImageOps

from app.core.config import settings

if TYPE_CHECKING:
    from onnxruntime import InferenceSession

DEFAULT_TIMEOUT_SECONDS = 5.0
BACKGROUND_TOLERANCE = 24
MODNET_MODEL = "modnet_photographic_portrait_matting.onnx"
BIREFNET_SIZE = (1024, 1024)
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
MODEL_SHORT_SIDE = 512
MODEL_MAX_SIDE = 1536
MODEL_ALIGNMENT = 32
_modnet_lock = Lock()
_birefnet_lock = Lock()
_sessions: dict[str, tuple[Path, InferenceSession]] = {}


def _get_session(model: str, lock: Lock) -> InferenceSession:
    path = settings.photo_models_dir / model
    with lock:
        cached = _sessions.get(model)
        if cached is None or cached[0] != path:
            if not path.is_file():
                hint = "请检查 PHOTO_MODELS_DIR"
                if model == MODNET_MODEL:
                    hint = "请在 backend 目录运行 uv run python -m scripts.download_models"
                raise FileNotFoundError(f"缺少抠图模型 {model}，{hint}")
            import onnxruntime as ort

            ort.disable_telemetry_events()
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            session = ort.InferenceSession(
                str(path), sess_options=options, providers=["CPUExecutionProvider"]
            )
            cached = _sessions[model] = (path, session)
        return cached[1]


def _get_modnet_session() -> InferenceSession:
    return _get_session(MODNET_MODEL, _modnet_lock)


def _encode_matting(image: Image.Image, alpha: np.ndarray) -> bytes:
    mask = Image.fromarray(np.round(np.clip(alpha, 0, 1) * 255).astype(np.uint8))
    mask = mask.resize(image.size, Image.Resampling.BILINEAR)
    image.putalpha(ImageChops.multiply(mask, image.getchannel("A")))
    with io.BytesIO() as buf:
        image.save(buf, format="PNG")
        return buf.getvalue()


class LocalMatting:
    """用 MODNet 在本机生成透明人像底片。"""

    def matte(self, data: bytes) -> bytes:
        session = _get_modnet_session()
        with Image.open(io.BytesIO(data)) as src:
            ImageOps.exif_transpose(src, in_place=True)
            # 普通照片以短边 512 推理。极端长宽比优先限制长边，控制内存。
            scale = min(MODEL_SHORT_SIDE / min(src.size), MODEL_MAX_SIDE / max(src.size))
            size = tuple(
                max(MODEL_ALIGNMENT, round(side * scale / MODEL_ALIGNMENT) * MODEL_ALIGNMENT)
                for side in src.size
            )
            resized = src.resize(size, Image.Resampling.BILINEAR).convert("RGB")
            image = src.convert("RGBA")
        model_input = np.asarray(resized, dtype=np.float32) / 127.5 - 1
        alpha = session.run(None, {session.get_inputs()[0].name: model_input.transpose(2, 0, 1)[None]})[0]
        return _encode_matting(image, alpha[0, 0])


class FineMatting:
    """用 BiRefNet 在本机生成精细人像底片。"""

    def matte(self, data: bytes) -> bytes:
        session = _get_session(settings.fine_matting_model, _birefnet_lock)
        with Image.open(io.BytesIO(data)) as src:
            ImageOps.exif_transpose(src, in_place=True)
            resized = src.convert("RGB").resize(BIREFNET_SIZE, Image.Resampling.BILINEAR)
            image = src.convert("RGBA")
        rgb = np.asarray(resized, dtype=np.float32) / 255
        normalized = (rgb - IMAGENET_MEAN) / IMAGENET_STD
        model_input = np.ascontiguousarray(normalized.transpose(2, 0, 1)[None])
        logits = session.run([session.get_outputs()[-1].name], {session.get_inputs()[0].name: model_input})[
            0
        ][0, 0]
        alpha = 1 / (1 + np.exp(-np.clip(logits, -80, 80)))
        return _encode_matting(image, alpha)


class MattingClient(Protocol):
    def matte(self, data: bytes) -> bytes:
        """接收原图字节并返回 RGBA PNG。外部服务调用超时抛 TimeoutError。"""
        ...


class FakeMatting:
    """开发联调用的纯色背景抠除，保留已有的透明通道。"""

    def matte(self, data: bytes) -> bytes:
        with Image.open(io.BytesIO(data)) as src:
            img = ImageOps.exif_transpose(src).convert("RGBA")
        if img.getchannel("A").getextrema()[0] == 255:
            rgb = img.convert("RGB")
            background = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
            red, green, blue = ImageChops.difference(rgb, background).split()
            distance = ImageChops.lighter(ImageChops.lighter(red, green), blue)
            img.putalpha(distance.point(lambda value: 0 if value <= BACKGROUND_TOLERANCE else 255))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


class RealMatting:
    def __init__(self, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    def matte(self, data: bytes) -> bytes:
        try:
            return self._request(data, timeout=self._timeout_seconds)
        except httpx.TimeoutException as exc:
            raise TimeoutError("抠图服务调用超时") from exc

    def _request(self, data: bytes, *, timeout: float) -> bytes:
        raise NotImplementedError("正式抠图服务待接入")


_local = LocalMatting()


def get_matting() -> MattingClient:
    if settings.matting_mode == "local":
        return _local
    if settings.matting_mode == "fake":
        return FakeMatting()
    return RealMatting(timeout_seconds=settings.matting_timeout_seconds)
