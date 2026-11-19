from datetime import datetime
from typing import Annotated

from pydantic import Field, StringConstraints

from app.core.schemas import Schema


class MeOut(Schema):
    """当前用户的个人资料。"""

    id: int = Field(description="用户 ID", examples=[1024])
    nickname: str | None = Field(description="昵称；还没设置时为空", examples=["小明"])
    avatar_url: str | None = Field(
        description="头像链接；还没设置时为空", examples=["https://example.com/a.png"]
    )
    phone_masked: str | None = Field(
        description="打码后的手机号，中间四位用 * 代替；没绑定手机号时为空", examples=["138****1234"]
    )
    has_phone: bool = Field(description="是否已绑定手机号", examples=[True])
    created_at: datetime = Field(description="注册时间（UTC，带时区）", examples=["2026-11-19T08:30:12Z"])


class UpdateMeRequest(Schema):
    """修改个人资料。只会修改传了的字段，没传的保持不变。"""

    nickname: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)] | None = (
        Field(
            default=None,
            description="新昵称，1～32 个字（首尾空格会去掉）；不传表示不修改",
            examples=["小明"],
        )
    )
    avatar_url: Annotated[str, StringConstraints(max_length=500, pattern=r"^https://\S+$")] | None = Field(
        default=None,
        description="新头像链接，必须是 https 开头，最长 500 个字符；不传表示不修改",
        examples=["https://example.com/a.png"],
    )


class BindPhoneRequest(Schema):
    """绑定手机号请求。"""

    code: str = Field(
        min_length=1,
        max_length=256,
        description="小程序里用户点“获取手机号”按钮（getPhoneNumber）拿到的 code，只能用一次",
        examples=["e1f2a3b4c5d6e7f8"],
    )


class CancelAccountRequest(Schema):
    """注销账号请求。"""

    confirm: bool = Field(
        description="用户确认注销，必须为 true，否则返回 VALIDATION_ERROR。注销后照片文件被删除、不可恢复",
        examples=[True],
    )
