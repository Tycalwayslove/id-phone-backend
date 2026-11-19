from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """健康检查结果。"""

    status: Literal["ok"] = Field(description="服务状态，能返回就固定为 ok", examples=["ok"])
    database: Literal["ok"] = Field(description="数据库状态，能执行查询时为 ok", examples=["ok"])
