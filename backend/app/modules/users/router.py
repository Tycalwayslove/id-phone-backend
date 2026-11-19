from fastapi import APIRouter

from app.core.deps import DB, Me
from app.core.errors import ErrorCode, errors_doc
from app.core.schemas import OkResponse
from app.modules.users import service
from app.modules.users.schemas import BindPhoneRequest, CancelAccountRequest, MeOut, UpdateMeRequest

router = APIRouter(tags=["我的"])

_AUTH_ERRORS = (ErrorCode.AUTH_REQUIRED, ErrorCode.AUTH_INVALID, ErrorCode.ACCOUNT_DISABLED)


@router.get(
    "/me",
    operation_id="users_me",
    summary="获取我的资料",
    description="返回当前登录用户的昵称、头像、打码手机号等。需要登录。",
    response_model=MeOut,
    response_description="当前用户资料",
    responses=errors_doc(*_AUTH_ERRORS),
)
def get_me(me: Me):
    return service.to_me_out(me.user)


@router.patch(
    "/me",
    operation_id="users_update_me",
    summary="修改我的资料",
    description="修改昵称和头像，只改传了的字段。需要登录。头像必须是 https 链接。",
    response_model=MeOut,
    response_description="修改后的用户资料",
    responses=errors_doc(*_AUTH_ERRORS, ErrorCode.VALIDATION_ERROR),
)
def update_me(body: UpdateMeRequest, me: Me, db: DB):
    return service.update_me(db, me.user, body)


@router.post(
    "/me/phone",
    operation_id="users_bind_phone",
    summary="绑定手机号",
    description=(
        "用小程序“获取手机号”按钮拿到的 code 绑定手机号。需要登录。"
        "手机号已被其他账号绑定时失败；重复绑定自己的号码或换绑新号码会直接覆盖。"
    ),
    response_model=MeOut,
    response_description="绑定后的用户资料",
    responses=errors_doc(
        *_AUTH_ERRORS,
        ErrorCode.WECHAT_LOGIN_FAILED,
        ErrorCode.PHONE_ALREADY_BOUND,
        ErrorCode.VALIDATION_ERROR,
    ),
)
def bind_phone(body: BindPhoneRequest, me: Me, db: DB):
    return service.bind_phone(db, me.user, body.code)


@router.post(
    "/me/cancel",
    operation_id="users_cancel",
    summary="注销账号",
    description=(
        "注销当前账号。需要登录，confirm 必须为 true。"
        "会删除该用户的全部照片文件、清空昵称头像手机号，并让所有设备的登录立即失效。不可恢复。"
    ),
    response_model=OkResponse,
    response_description="注销成功",
    responses=errors_doc(*_AUTH_ERRORS, ErrorCode.VALIDATION_ERROR),
)
def cancel_account(body: CancelAccountRequest, me: Me, db: DB):
    service.cancel_account(db, me.user, body.confirm)
    return OkResponse()
