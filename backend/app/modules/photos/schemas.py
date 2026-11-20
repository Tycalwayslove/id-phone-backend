"""照片模块的请求和返回模型。"""

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.core.schemas import Schema, page_model


class UploadOut(Schema):
    """上传结果。拿 file_id 去创建照片。"""

    file_id: int = Field(
        description="上传文件的 ID，下一步创建照片时传入；未使用的上传会被定期清理", examples=[101]
    )
    width: int = Field(description="图片宽度，单位像素", examples=[600])
    height: int = Field(description="图片高度，单位像素", examples=[800])


class PhotoCreate(Schema):
    """创建照片的请求。"""

    file_id: int = Field(
        description="上传接口返回的 file_id；必须是自己上传的、还没被其他照片使用的原图", examples=[101]
    )
    source: Literal["camera", "upload"] = Field(
        description="照片来源。camera = 小程序内拍照；upload = 从相册选择", examples=["camera"]
    )


class AccessOut(Schema):
    """这张照片当前的权益状态。"""

    active: bool = Field(
        description="保管期内是否有效；false 表示未付费或已到期，只能看带水印预览，不能下载", examples=[True]
    )
    access_until: datetime | None = Field(
        default=None, description="保管到期时间；从未付费时为空", examples=["2027-11-19T08:30:00Z"]
    )
    spec_change: bool = Field(
        description="是否允许更换规格（用同一张底片导出其他规格的无水印图）", examples=[True]
    )


QualityCode = Literal[
    "no_face",
    "multiple_faces",
    "face_too_small",
    "face_off_center",
    "too_dark",
    "too_bright",
    "not_frontal",
    "uneven_light",
]


class QualityIssue(Schema):
    """拍后检测发现的一项问题。"""

    code: QualityCode = Field(
        description=(
            "问题编码。no_face = 未检测到人脸，multiple_faces = 检测到多张人脸，"
            "face_too_small = 脸太小，face_off_center = 脸偏离轮廓框，too_dark = 脸太暗，"
            "too_bright = 脸太亮，not_frontal = 没正对镜头，uneven_light = 左右脸光照不均。"
        ),
        examples=["face_too_small"],
    )
    message: str = Field(
        description="可直接提示用户的中文问题和重拍建议", examples=["脸有点小，请靠近一点再拍"]
    )


class PhotoQuality(Schema):
    """本地拍后快速检测结果，用于提示用户调整照片。"""

    level: Literal["ok", "warn", "fail"] = Field(
        description="检测等级。ok = 合格，无需提示。warn = 有建议，可继续制作。fail = 建议重拍，用户仍可继续。",
        examples=["warn"],
    )
    issues: list[QualityIssue] = Field(description="检测发现的问题，合格时为空列表")


class PhotoOut(Schema):
    """一张照片（底片）。"""

    id: int = Field(description="照片 ID", examples=[12])
    source: Literal["camera", "upload"] = Field(
        description="来源。camera = 小程序内拍照；upload = 从相册选择", examples=["camera"]
    )
    status: Literal["draft", "active", "expired", "purged"] = Field(
        description=(
            "照片状态。active = 已创建；expired = 保管期已过；"
            "draft = 上传待创建的草稿，purged = 已删除，这两种状态不会返回。"
        ),
        examples=["active"],
    )
    created_at: datetime = Field(description="创建时间", examples=["2026-11-19T08:30:00Z"])
    original_url: str = Field(
        description="原图的临时访问链接，约 10 分钟内有效；内容检测通过后才返回链接，否则为空字符串",
        examples=["https://api.example.com/files/..."],
    )
    access: AccessOut = Field(description="权益状态，决定能否下载、能否换规格")
    matting_level: Literal["fast", "fine", "failed"] | None = Field(
        description=(
            "抠图精度。fast = 可制作，正在等待或执行精细抠图。fine = 精细底片已就绪。"
            "failed = 精细抠图失败，继续使用原有底片。上线前创建或未启用精细抠图的照片为空。"
        ),
        examples=["fast"],
    )
    quality: PhotoQuality | None = Field(
        default=None,
        description="创建时的本地拍后检测结果。缺少检测结果时为空，例如这项功能上线前创建的照片。",
    )


PhotoPage = page_model(PhotoOut, "PhotoPage")


class RenderOut(Schema):
    """一张导出图：某张照片按某个规格、底色、美颜档位导出的结果。"""

    id: int = Field(description="导出图 ID", examples=[7])
    spec_code: str = Field(description="规格编码", examples=["gd_idcard"])
    spec_name: str = Field(description="规格名称", examples=["广东省身份证"])
    bg_color: str = Field(description="底色，十六进制颜色值", examples=["#FFFFFF"])
    beauty_level: int = Field(description="美颜档位，0 表示只自动校正光影", examples=[0])
    watermarked: bool = Field(
        description="是否带水印。true 为预览图，不能下载；false 为正式图，权益有效期内可下载", examples=[True]
    )
    width_px: int = Field(description="图片宽度，单位像素", examples=[358])
    height_px: int = Field(description="图片高度，单位像素", examples=[441])
    size_bytes: int = Field(description="文件大小，单位字节", examples=[48210])
    preview_url: str = Field(
        description="图片的临时访问链接，约 10 分钟内有效，用于在页面上显示",
        examples=["https://api.example.com/files/..."],
    )


class PhotoDetail(PhotoOut):
    """照片详情：在照片基础上带上全部导出图。"""

    renders: list[RenderOut] = Field(
        description="已生成的导出图，按生成时间从早到晚；保管期过后只保留带水印的预览图，内容检测未通过时为空"
    )


class BlemishPoint(Schema):
    """用户在成品图上点选的一处痘印。"""

    x: float = Field(
        ge=0, le=1, strict=True, description="成品图横坐标，从左到右归一化至 0～1", examples=[0.34]
    )
    y: float = Field(
        ge=0, le=1, strict=True, description="成品图纵坐标，从上到下归一化至 0～1", examples=[0.52]
    )


class RenderCreate(Schema):
    """生成导出图的请求。"""

    spec_code: str = Field(description="规格编码，来自规格列表", max_length=64, examples=["gd_idcard"])
    bg_color: str | None = Field(
        default=None,
        description="底色，必须是该规格 bg_colors 里的一个（不区分大小写）；不传取第一个",
        max_length=16,
        examples=["#FFFFFF"],
    )
    beauty_level: int = Field(
        default=0,
        ge=0,
        le=5,
        description="美颜档位，0 表示只自动校正光影。最高为该规格的 beauty_max。",
        examples=[0],
    )
    blemishes: list[BlemishPoint] = Field(
        default_factory=list,
        max_length=10,
        description="用户在当前规格成品图上点选的祛痘位置，最多 10 个。省略或空数组表示不祛痘。",
        examples=[[{"x": 0.34, "y": 0.52}]],
    )


class DownloadOut(Schema):
    """下载链接。"""

    url: str = Field(
        description="无水印图片的临时下载链接，10 分钟内有效", examples=["https://api.example.com/files/..."]
    )
    expires_at: datetime = Field(description="链接过期时间", examples=["2026-11-19T08:40:00Z"])


class WechatMediaResult(Schema):
    """微信图片内容检测的综合结果。"""

    suggest: str = Field(
        description="处理建议，pass 为通过、risky 为有风险、review 为需要复核", examples=["pass"]
    )


class WechatMediaEvent(Schema):
    """小程序消息推送，使用明文 JSON 格式。"""

    message_type: str = Field(alias="MsgType", description="消息类型，event 为事件", examples=["event"])
    event: str | None = Field(
        default=None,
        alias="Event",
        description="事件名，wxa_media_check 为图片内容检测",
        examples=["wxa_media_check"],
    )
    app_id: str | None = Field(
        default=None, alias="appid", description="发送检测请求的小程序 AppID", examples=["wx-dev-app"]
    )
    trace_id: str | None = Field(
        default=None, description="提交检测时返回的任务 ID", examples=["6281cfed-3a6f-b1d3"]
    )
    errcode: int | None = Field(
        default=None, strict=True, description="检测错误码，0 表示结果有效", examples=[0]
    )
    result: WechatMediaResult | None = Field(default=None, description="检测成功时的综合结果")
