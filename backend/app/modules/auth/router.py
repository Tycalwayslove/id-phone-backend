from fastapi import APIRouter, Request

from app.core.deps import DB, Me
from app.core.errors import ErrorCode, errors_doc
from app.core.schemas import OkResponse
from app.modules.auth import service
from app.modules.auth.schemas import LoginResponse, WechatMiniLoginRequest

router = APIRouter(tags=["登录"])


@router.post(
    "/auth/wechat-mini/login",
    operation_id="auth_wechat_mini_login",
    summary="微信小程序登录",
    description=(
        "用 wx.login() 拿到的 code 换取登录令牌。不需要登录。"
        "第一次登录会自动创建用户（返回 user.is_new=true）；同一个微信再次登录得到同一个用户。"
        "已注销的账号再次登录视为全新用户。账号被停用时不能登录。"
    ),
    response_model=LoginResponse,
    response_description="登录成功，返回令牌和用户信息",
    responses=errors_doc(ErrorCode.WECHAT_LOGIN_FAILED, ErrorCode.ACCOUNT_DISABLED),
)
def wechat_mini_login(body: WechatMiniLoginRequest, request: Request, db: DB):
    return service.wechat_mini_login(
        db,
        code=body.code,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )


@router.post(
    "/auth/logout",
    operation_id="auth_logout",
    summary="退出登录",
    description="吊销当前令牌，之后用它访问任何需要登录的接口都会返回 AUTH_INVALID。需要登录。其他设备上的登录不受影响。",
    response_model=OkResponse,
    response_description="退出成功",
    responses=errors_doc(ErrorCode.AUTH_REQUIRED, ErrorCode.AUTH_INVALID, ErrorCode.ACCOUNT_DISABLED),
)
def logout(me: Me, db: DB):
    service.logout(db, session_id=me.session_id)
    return OkResponse()
