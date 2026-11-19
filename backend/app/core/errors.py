from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """所有接口出错时的统一返回格式。前端按 code 判断错误类型，message 可以直接展示给用户。"""

    code: str = Field(description="错误码，全大写下划线，如 QUOTA_EXHAUSTED", examples=["DB_UNAVAILABLE"])
    message: str = Field(description="给用户看的错误说明", examples=["数据库暂时不可用，请稍后再试"])


def error_doc(description: str) -> dict:
    """在路由的 responses 里声明一个错误返回，供接口文档展示。"""
    return {"model": ErrorResponse, "description": description}
