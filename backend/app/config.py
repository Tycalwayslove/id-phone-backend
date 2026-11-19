from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """所有配置都来自环境变量或 .env。换环境（本机 → 服务器）只改配置，不改代码。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 运行环境：dev 本机开发，test 自动化测试，prod 服务器
    app_env: Literal["dev", "test", "prod"] = "dev"
    database_url: str
    # 打印每条 SQL，只在本机排查问题时临时打开
    db_echo: bool = False

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"


settings = Settings()
