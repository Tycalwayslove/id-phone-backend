import pytest

from app.modules.admin import service


@pytest.fixture(autouse=True)
def _reset_login_limiter():
    """登录失败记录在进程内存里，测试之间要清空。"""
    service.reset_login_limiter()
    yield
    service.reset_login_limiter()
