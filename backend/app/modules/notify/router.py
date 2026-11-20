from fastapi import APIRouter

from app.core.deps import DB, Me
from app.core.errors import ErrorCode, errors_doc
from app.modules.notify import service
from app.modules.notify.schemas import SubscriptionQuota, SubscriptionReport, TemplateOut

router = APIRouter(tags=["通知"])

_AUTH_ERRORS = (ErrorCode.AUTH_REQUIRED, ErrorCode.AUTH_INVALID, ErrorCode.ACCOUNT_DISABLED)


@router.get(
    "/notify/templates",
    operation_id="notify_templates",
    summary="订阅消息模板列表",
    description=(
        "返回小程序需要向用户申请授权的订阅消息模板（固定几个，一次返回全部、不分页）。需要登录。"
        "前端在用户提交回执申请前，用这里的 template_id 调 wx.requestSubscribeMessage，"
        "再调用“上报订阅授权”接口把用户点了允许的模板告诉后端，办理结果出来后才能通知到用户。"
    ),
    response_model=list[TemplateOut],
    response_description="需要授权的模板列表",
    responses=errors_doc(*_AUTH_ERRORS),
)
def notify_templates(me: Me):
    return service.list_templates()


@router.post(
    "/notify/subscriptions",
    operation_id="notify_report_subscriptions",
    summary="上报订阅授权",
    description=(
        "上报用户在订阅消息弹窗里点了“允许”的模板。需要登录。"
        "每个模板每次授权累计 1 次发送机会，发一条通知消耗 1 次；"
        "不在模板列表里的 ID 会被忽略；用户没有小程序身份时返回空的 quota。"
    ),
    response_model=SubscriptionQuota,
    response_description="各模板当前剩余的授权次数",
    responses=errors_doc(*_AUTH_ERRORS),
)
def notify_report_subscriptions(body: SubscriptionReport, me: Me, db: DB):
    return service.report_subscriptions(db, user_id=me.id, accepted=body.accepted)
