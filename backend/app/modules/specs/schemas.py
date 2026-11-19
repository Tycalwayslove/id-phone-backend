"""规格模块的请求和返回模型。"""

from typing import Literal

from pydantic import ConfigDict, Field

from app.core.schemas import Schema, page_model


class SpecOut(Schema):
    """规格摘要：列表里每一项。"""

    code: str = Field(description="规格编码，唯一，接口里用它指定规格", examples=["gd_idcard"])
    name: str = Field(description="规格名称，直接展示给用户", examples=["广东省身份证"])
    category: Literal["receipt", "normal", "exam"] = Field(
        description=(
            "规格分类。receipt = 回执类（身份证、社保卡、驾驶证等，可办理官方照片回执）；"
            "normal = 普通证件照（一寸、二寸、签证等）；exam = 考试报名照（公务员、教资等）"
        ),
        examples=["receipt"],
    )
    cert_type: str = Field(
        description="证件类型标识，如 idcard、driver_license，前端可据此显示图标", examples=["idcard"]
    )
    region_code: str | None = Field(
        default=None, description="适用地区的行政区划码；为空表示不限地区", examples=["440000"]
    )
    width_px: int = Field(description="成品宽度，单位像素", examples=[358])
    height_px: int = Field(description="成品高度，单位像素", examples=[441])
    width_mm: int | None = Field(
        default=None, description="成品宽度，单位毫米；官方未规定时为空", examples=[26]
    )
    height_mm: int | None = Field(
        default=None, description="成品高度，单位毫米；官方未规定时为空", examples=[32]
    )


SpecPage = page_model(SpecOut, "SpecPage")


class SpecFormField(Schema):
    """办理回执时需要用户填写的一个字段。"""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    key: str = Field(description="字段标识，提交回执时作为表单键名", examples=["name"])
    label: str = Field(description="字段名称，直接展示给用户", examples=["姓名"])
    required: bool = Field(default=True, description="是否必填", examples=[True])


class SpecDetail(SpecOut):
    """规格详情：在摘要基础上增加底色、文件大小、美颜上限、回执表单等。"""

    dpi: int = Field(description="成品分辨率，单位 dpi（每英寸像素数）", examples=[300])
    bg_colors: list[str] = Field(
        description="可选底色列表，十六进制颜色值；制作时 bg_color 必须取自这里，第一项是默认底色",
        examples=[["#FFFFFF", "#438EDB"]],
    )
    file_size_min_kb: int | None = Field(
        default=None, description="官方要求的文件大小下限，单位 KB；无要求时为空", examples=[None]
    )
    file_size_max_kb: int | None = Field(
        default=None, description="官方要求的文件大小上限，单位 KB；无要求时为空", examples=[100]
    )
    beauty_max: int = Field(
        description="允许的最高美颜档位，0～5；0 表示该规格不允许美颜（如官方要求不得修图）", examples=[3]
    )
    form_schema: list[SpecFormField] = Field(
        description="办理回执时要用户填写的字段列表；不支持回执的规格通常为空列表"
    )
    supports_receipt: bool = Field(
        description="当前是否能办理该规格的官方回执（有启用的服务商通道）；false 时不要展示办理入口",
        examples=[True],
    )
    official_valid_days: int | None = Field(
        default=None, description="官方回执的有效天数；无明确期限时为空", examples=[90]
    )
