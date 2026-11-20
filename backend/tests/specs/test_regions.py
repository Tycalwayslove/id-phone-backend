import pytest

from app.core.regions import province_of, region_name, resolve_region


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("广州市社保证", "440100"),
        ("广东广州驾驶证", "440100"),
        ("贵州身份证", "520000"),
        ("吉林省身份证", "220000"),
        ("吉林省吉林市身份证", "220200"),
        ("鄂州呼伦贝尔报名照", "150700"),
        ("广西壮族自治区身份证", "450000"),
        ("北京市社保卡", "110000"),
        ("普通小一寸", None),
    ],
)
def test_resolve_region(name, code):
    assert resolve_region(name) == code


def test_region_lookup():
    assert province_of("440100") == province_of("440000") == "440000"
    assert province_of("110000") == "110000"
    assert province_of("999999") is None
    assert region_name("440100") == "广州市"
    assert region_name(None) is None
