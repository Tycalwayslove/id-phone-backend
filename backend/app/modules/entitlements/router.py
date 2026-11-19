from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from app.core.deps import DB, Me
from app.core.errors import ErrorCode, errors_doc
from app.modules.entitlements import service
from app.modules.entitlements.schemas import EntitlementOut

router = APIRouter(tags=["权益"])


@router.get(
    "/entitlements",
    operation_id="entitlements_list",
    summary="我的权益列表",
    description=(
        "返回当前用户买到的权益（保管期、回执次数等），按到期时间从晚到早排序，最多 100 条，不分页。"
        "需要登录。默认只返回当前有效的权益；传 status=expired 查已到期的（用于展示“续费”），status=all 查全部。"
    ),
    response_model=list[EntitlementOut],
    response_description="权益列表，没有则为空数组",
    responses=errors_doc(ErrorCode.AUTH_REQUIRED, ErrorCode.AUTH_INVALID),
)
def list_entitlements(
    me: Me,
    db: DB,
    status: Annotated[
        Literal["active", "expired", "all"],
        Query(
            description=(
                "按状态过滤。active：有效（状态正常且未到期，默认）；expired：已到期或已撤销；all：全部"
            )
        ),
    ] = "active",
):
    return service.list_entitlements(db, me.id, status)


@router.get(
    "/entitlements/{entitlement_id}",
    operation_id="entitlements_detail",
    summary="权益详情",
    description="按 ID 查看当前用户的一份权益。需要登录。别人的权益或不存在的 ID 都返回 ENTITLEMENT_NOT_FOUND。",
    response_model=EntitlementOut,
    response_description="权益详情",
    responses=errors_doc(ErrorCode.AUTH_REQUIRED, ErrorCode.AUTH_INVALID, ErrorCode.ENTITLEMENT_NOT_FOUND),
)
def get_entitlement(
    entitlement_id: Annotated[int, Path(description="权益 ID，来自权益列表", examples=[12])],
    me: Me,
    db: DB,
):
    return service.get_entitlement(db, me.id, entitlement_id)
