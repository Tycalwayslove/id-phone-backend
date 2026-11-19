from datetime import datetime

from pydantic import Field

from app.core.schemas import Schema


class WechatMiniLoginRequest(Schema):
    """微信小程序登录请求。"""

    code: str = Field(
        min_length=1,
        max_length=256,
        description="小程序调用 wx.login() 拿到的临时登录凭证，只能用一次、几分钟内有效",
        examples=["0a3Xyz1w3abcd2mQ"],
    )


class LoginUserOut(Schema):
    """登录后返回的用户简要信息。"""

    id: int = Field(description="用户 ID", examples=[1024])
    nickname: str | None = Field(description="昵称；用户还没设置时为空", examples=["小明"])
    avatar_url: str | None = Field(
        description="头像链接；还没设置时为空", examples=["https://example.com/a.png"]
    )
    phone_masked: str | None = Field(
        description="打码后的手机号；还没绑定手机号时为空", examples=["138****1234"]
    )
    is_new: bool = Field(
        description="是否本次登录刚创建的新用户。true 表示首次登录，前端可走新用户引导",
        examples=[True],
    )


class LoginResponse(Schema):
    """登录成功的返回：令牌和用户信息。"""

    token: str = Field(
        description="登录令牌。之后每个需要登录的接口都在请求头带 Authorization: Bearer <token>；不要放进 URL",
        examples=["q3mJ0s2kT9x8Yb7wVnC1aZpL4dRfE6uHgIoKjXcMvBQ"],
    )
    expires_at: datetime = Field(
        description="令牌当前的闲置过期时间（UTC，带时区）。持续使用会自动顺延，但最长不超过绝对有效期",
        examples=["2026-11-26T08:30:12Z"],
    )
    user: LoginUserOut = Field(description="当前登录的用户信息")
