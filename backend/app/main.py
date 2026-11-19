"""应用入口：挂载各模块路由、统一错误处理。

每个模块在 app/modules/<name>/router.py 里可以导出四种路由（没有就不导出）：
- router           C 端接口，挂在 /api/v1
- admin_router     后台接口，挂在 /api/v1/admin
- callback_router  第三方回调（支付、回执服务商），挂在 /api/v1/callbacks
- dev_router       联调用的模拟接口，挂在 /api/v1/dev，生产环境不挂
"""

import importlib

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.core.config import settings
from app.core.errors import ErrorCode, error_catalog_markdown, error_doc, install_error_handlers
from app.modules.system.router import files_router
from app.modules.system.router import router as system_router

MODULES = ["auth", "users", "specs", "photos", "orders", "entitlements", "receipts", "notify", "admin"]

# 每个 tag 在 Apifox 里是一个目录
TAGS = [
    {"name": "系统", "description": "健康检查、文件下载等，不需要登录"},
    {"name": "登录", "description": "小程序登录、退出"},
    {"name": "我的", "description": "当前用户的资料、手机号、注销账号"},
    {"name": "规格", "description": "证件照规格库，不登录也能查"},
    {"name": "照片", "description": "上传、制作证件照、换规格、下载"},
    {"name": "套餐与订单", "description": "套餐列表、下单、支付、订单查询"},
    {"name": "权益", "description": "用户买到的权益：保管期、回执次数"},
    {"name": "回执", "description": "回执办理、驳回重提、查看回执"},
    {"name": "通知", "description": "订阅消息授权上报"},
    {"name": "后台", "description": "运营后台接口，需要后台账号登录"},
    {"name": "回调", "description": "支付和回执服务商的结果通知，由第三方调用"},
    {"name": "联调", "description": "仅开发和测试环境可用：模拟支付成功、模拟回执结果"},
]


def _missing_operation_id(route: APIRoute) -> str:
    # 没写 operation_id 的接口会得到这个标记，scripts/check_api_docs.py 会把它查出来
    return f"MISSING_OPERATION_ID__{route.name}"


DESCRIPTION = f"""证件照制作、回执办理、权益和订单相关接口。

- C 端接口需要登录的，请求头带 `Authorization: Bearer <token>`（登录接口返回）。
- 后台接口使用登录后写入的 Cookie，修改类请求还要带 `X-CSRF-Token`。
- 金额单位一律是分（字段名以 `_fen` 结尾）；时间是带时区的 ISO 8601。
- 列表接口用游标翻页：第一页不传 cursor，之后传上一页的 next_cursor。
- 出错时统一返回 `{{"code": "...", "message": "..."}}`，前端按 code 处理。

## 错误码

{error_catalog_markdown()}
"""

_docs = not settings.is_prod
app = FastAPI(
    title="证件照与回执 API",
    description=DESCRIPTION,
    version="0.2.0",
    openapi_tags=TAGS,
    generate_unique_id_function=_missing_operation_id,
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)
install_error_handlers(app)

# 所有 /api/v1 接口都可能返回参数校验错误
_common = {422: error_doc(ErrorCode.VALIDATION_ERROR)}

app.include_router(system_router)
app.include_router(files_router)
for name in MODULES:
    mod = importlib.import_module(f"app.modules.{name}.router")
    if r := getattr(mod, "router", None):
        app.include_router(r, prefix="/api/v1", responses=_common)
    if r := getattr(mod, "admin_router", None):
        app.include_router(r, prefix="/api/v1/admin", responses=_common)
    if r := getattr(mod, "callback_router", None):
        app.include_router(r, prefix="/api/v1/callbacks")
    if (r := getattr(mod, "dev_router", None)) and not settings.is_prod:
        app.include_router(r, prefix="/api/v1/dev", responses=_common)
