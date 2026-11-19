"""各模块共用的返回结构。"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model


class Schema(BaseModel):
    """所有请求/返回模型的基类：可以直接从 ORM 对象构造（model_validate(obj)）。"""

    model_config = ConfigDict(from_attributes=True)


class OkResponse(Schema):
    """只表示操作成功、没有其他数据的返回。"""

    ok: bool = Field(default=True, description="固定为 true")


def page_model(item: type[BaseModel], name: str) -> Any:
    """生成分页返回模型。name 会成为接口文档里的模型名，如 PhotoPage。

    用法：PhotoPage = page_model(PhotoOut, "PhotoPage")
    """
    first_line = (item.__doc__ or name).strip().splitlines()[0]
    model = create_model(
        name,
        __base__=Schema,
        __doc__=f"分页列表：{first_line}",
        items=(list[item], Field(description="本页数据，按创建时间从新到旧")),
        next_cursor=(str | None, Field(default=None, description="下一页游标；为空表示没有更多了")),
    )
    return model
