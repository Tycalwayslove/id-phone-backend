import sys
from unittest.mock import Mock

import httpx

from app.models import Spec
from scripts import eval_pipeline
from tests.photos.helpers import jpeg_bytes, png_rgba_bytes


def test_check_without_yes_builds_local_report_only(monkeypatch, tmp_path, capsys):
    source = tmp_path / "input"
    source.mkdir()
    (source / "portrait<test>.jpg").write_bytes(jpeg_bytes())
    spec = Spec(code="test_spec", width_px=358, height_px=441, bg_colors=["#FFFFFF"], dpi=300, beauty_max=2)
    monkeypatch.setattr(eval_pipeline, "EVAL_DIR", tmp_path)
    loaded = Mock(return_value=([spec], {spec.code: "123"}))
    monkeypatch.setattr(eval_pipeline, "_load_specs", loaded)
    monkeypatch.setattr(eval_pipeline, "detect_faces", lambda image: [])
    monkeypatch.setattr(eval_pipeline.LocalMatting, "matte", lambda self, data: png_rgba_bytes())
    client = Mock()
    monkeypatch.setattr(eval_pipeline.httpx, "Client", client)
    monkeypatch.setattr(
        sys,
        "argv",
        ["eval_pipeline", "--input", str(source), "--spec", spec.code, "--check", "--beauty", "0,2,4"],
    )

    eval_pipeline.main()

    client.assert_not_called()
    loaded.assert_called_once_with([spec.code], with_mapping=True)
    assert "将调用 2 次，预计 0.024 元" in capsys.readouterr().out
    (report,) = (tmp_path / "output").glob("*/report.html")
    html = report.read_text()
    assert "portrait&lt;test&gt;.jpg" in html
    assert "档位 0" in html and "档位 2" in html
    assert "超过规格上限" in html and "档位 4" in html
    assert "没有检测到人脸" in html
    for name in ("original.jpg", "matting.png", "render-001.jpg", "render-002.jpg"):
        assert (report.parent / "001" / name).is_file()


def test_provider_check_uses_form_and_reads_failed_items(monkeypatch):
    monkeypatch.setattr(eval_pipeline.settings, "zheying_api_base", "https://provider.example.test")
    monkeypatch.setattr(eval_pipeline.settings, "zheying_app_key", "test-key")

    def respond(request):
        assert request.method == "POST" and request.url.path == "/idphoto/check"
        assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
        form = request.content.split(b"&")
        assert b"item_id=123" in form and b"key=test-key" in form
        assert any(field.startswith(b"image=") for field in form)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "passed_status": 0,
                    "passed_list": [
                        {"key": "dpi", "passed": 1, "msg": "通过"},
                        {"key": "lighting", "passed": 0, "msg": "光线不均<测试>"},
                    ],
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = eval_pipeline._check(client, b"fake-jpeg", "123")

    assert result.passed is False
    assert result.issues == (("lighting", "光线不均<测试>"),)
    assert "光线不均&lt;测试&gt;" in result.to_html()
