import pytest
from pydantic import ValidationError

from app.core.config import Settings

REAL = {
    "app_env": "prod",
    "wechat_mode": "real",
    "media_check_mode": "real",
    "pay_mode": "wechat",
    "receipt_mode": "real",
    "secret_key": "prod-secret-not-default-0123456789abcdef",
}


def test_prod_rejects_fake_media_check():
    with pytest.raises(ValidationError, match="MEDIA_CHECK_MODE"):
        Settings(_env_file=None, **{**REAL, "media_check_mode": "fake"})


def test_dev_allows_real_login_with_fake_media_check():
    s = Settings(_env_file=None, app_env="dev", wechat_mode="real", media_check_mode="fake")
    assert (s.wechat_mode, s.media_check_mode) == ("real", "fake")
