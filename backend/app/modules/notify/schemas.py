"""通知模块的请求和返回模型。"""

from typing import Literal

from pydantic import Field

from app.core.schemas import Schema


class TemplateOut(Schema):
    """一个需要用户授权的订阅消息模板。"""

    event: Literal["receipt_completed", "receipt_rejected"] = Field(
        description="这个模板对应的通知事件。receipt_completed = 回执办理成功；receipt_rejected = 回执被驳回",
        examples=["receipt_rejected"],
    )
    template_id: str = Field(
        description="小程序订阅消息模板 ID，传给 wx.requestSubscribeMessage 的 tmplIds",
        examples=["TMPL_RECEIPT_REJECTED_PLACEHOLDER"],
    )
    title: str = Field(description="模板名称，可展示在授权提示文案里", examples=["回执被驳回提醒"])


class SubscriptionReport(Schema):
    """上报用户在订阅消息弹窗里点了“允许”的模板。"""

    accepted: list[str] = Field(
        description=(
            "用户点了“允许”的模板 ID 列表，来自 wx.requestSubscribeMessage 返回值里取值为 accept 的模板；"
            "不在模板列表里的 ID 会被忽略，重复的 ID 只计一次"
        ),
        max_length=20,
        examples=[["TMPL_RECEIPT_REJECTED_PLACEHOLDER"]],
    )


class SubscriptionQuota(Schema):
    """当前用户各订阅消息模板的剩余授权次数。"""

    quota: dict[str, int] = Field(
        description="key 是模板 ID，value 是剩余可发送次数（一次授权发一条）；用户没有小程序身份时为空对象",
        examples=[{"TMPL_RECEIPT_REJECTED_PLACEHOLDER": 1}],
    )
