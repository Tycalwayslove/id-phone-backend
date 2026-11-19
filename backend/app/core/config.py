from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """所有配置都来自环境变量或 .env。换环境（本机 → 服务器）只改配置，不改代码。

    外部服务（微信、支付、存储、回执服务商）都有 fake 模式：没有正式账号时也能把整条链路跑通。
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 运行环境：dev 本机开发，test 自动化测试，prod 服务器
    app_env: Literal["dev", "test", "prod"] = "dev"
    database_url: str
    db_echo: bool = False

    # 对外访问的地址，用来拼文件下载链接，如 https://api.example.com
    public_base_url: str = "http://localhost:8000"
    # 签名、加密用的主密钥。生产环境必须换成随机长串：openssl rand -hex 32
    secret_key: str = Field(default="dev-only-secret-change-me-0123456789abcdef", min_length=32)

    # 会话：多少天不用就失效、最长多少天
    session_idle_days: int = 7
    session_absolute_days: int = 30
    admin_session_idle_hours: int = 2
    admin_session_absolute_hours: int = 12

    # 微信小程序登录
    wechat_mode: Literal["fake", "real"] = "fake"
    wx_mini_app_id: str = "wx-dev-app"
    wx_mini_app_secret: str = ""

    # 微信支付
    pay_mode: Literal["fake", "wechat"] = "fake"
    wxpay_mch_id: str = ""
    wxpay_api_v3_key: str = ""
    wxpay_cert_serial: str = ""
    wxpay_private_key_path: str = ""
    wxpay_platform_cert_path: str = ""

    # 文件存储：local 存在本机目录，oss 存阿里云 OSS
    storage_mode: Literal["local", "oss"] = "local"
    local_storage_dir: str = "storage"
    oss_endpoint: str = ""
    oss_bucket: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""

    # 抠图与美颜：fake 时直接用原图
    matting_mode: Literal["fake", "zheying"] = "fake"

    # 回执服务商：fake 模式下提交后自动出回执，用来联调
    receipt_mode: Literal["fake", "real"] = "fake"
    zheying_api_base: str = "https://api.zjzapi.com"
    zheying_app_key: str = ""
    zheying_app_secret: str = ""
    clipimg_api_base: str = "https://www.qwyun.top"
    clipimg_app_key: str = ""
    clipimg_app_secret: str = ""

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"


settings = Settings()
