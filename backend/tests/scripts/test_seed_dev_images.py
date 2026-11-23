from hashlib import sha256
from io import BytesIO

from PIL import Image

from app.integrations.storage import LocalStorage
from app.models import File
from scripts import seed_dev


def test_seed_demo_images_are_readable_and_preserve_existing_files(monkeypatch, tmp_path):
    storage = LocalStorage(str(tmp_path))
    monkeypatch.setattr(seed_dev, "get_storage", lambda: storage)
    for key, mime, image, mode in (
        ("original.jpg", "image/jpeg", seed_dev.demo_portrait((600, 800), "#FFFFFF", 1), "RGB"),
        ("matting.png", "image/png", seed_dev.demo_portrait((600, 800), None, 2), "RGBA"),
        ("receipt.png", "image/png", seed_dev.demo_receipt(), "RGB"),
    ):
        file = File(storage_key=key, mime=mime)
        seed_dev.write_demo_image(file, image)
        original = storage.get(key)
        with Image.open(BytesIO(original)) as stored:
            stored.load()
            assert stored.mode == mode and stored.size == image.size

        seed_dev.write_demo_image(file, Image.new("RGB", image.size, "black"))
        assert storage.get(key) == original
        assert file.size_bytes == len(original)
        assert file.sha256 == sha256(original).hexdigest()
