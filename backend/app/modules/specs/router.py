from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from app.core.deps import DB, Page
from app.core.errors import ErrorCode, errors_doc
from app.modules.specs import service
from app.modules.specs.schemas import SpecDetail, SpecPage, SpecRegionProvince

router = APIRouter(tags=["规格"])


@router.get(
    "/specs",
    operation_id="specs_list",
    summary="规格列表",
    description=(
        "分页列出可用的证件照规格，按后台设置的顺序排列。不需要登录。"
        "只返回已上架的规格；可按分类、名称关键字和地区筛选。"
    ),
    response_model=SpecPage,
    response_description="本页规格和下一页游标",
)
def list_specs(
    db: DB,
    page: Page,
    category: Annotated[
        Literal["receipt", "normal", "exam"] | None,
        Query(
            description=(
                "按分类筛选，不传返回全部。receipt = 回执类（身份证、社保卡、驾驶证等，可办官方回执）；"
                "normal = 普通证件照（一寸、二寸、签证等）；exam = 考试报名照"
            ),
            examples=["receipt"],
        ),
    ] = None,
    keyword: Annotated[
        str | None,
        Query(max_length=50, description="按规格名称模糊搜索，不区分大小写；不传不过滤", examples=["身份证"]),
    ] = None,
    region_code: Annotated[
        str | None,
        Query(
            pattern=r"^[0-9]{6}$",
            description="6 位省或市行政区划码。选市返回全国通用、该省和该市规格。选省返回全国通用和该省规格。不传返回全部地区。",
            examples=["440100"],
        ),
    ] = None,
):
    return service.list_specs(db, category=category, keyword=keyword, page=page, region_code=region_code)


@router.get(
    "/spec-regions",
    operation_id="spec_regions_list",
    summary="规格地区列表",
    description=(
        "按省汇总有已上架地区专属规格的省、市及规格数，供选择地区。不需要登录。"
        "忽略全国通用规格和未收录的区划码，省和市各按区划码排序。"
    ),
    response_model=list[SpecRegionProvince],
    response_description="有地区专属规格的省及其市列表",
)
def list_spec_regions(db: DB):
    return service.list_spec_regions(db)


@router.get(
    "/specs/{code}",
    operation_id="specs_detail",
    summary="规格详情",
    description=(
        "按规格编码查询详情：尺寸、可选底色、文件大小要求、美颜上限、回执表单字段，"
        "以及当前能否办理回执（supports_receipt）。不需要登录。规格不存在或已下架返回 SPEC_NOT_FOUND。"
    ),
    response_model=SpecDetail,
    response_description="规格详情",
    responses=errors_doc(ErrorCode.SPEC_NOT_FOUND),
)
def spec_detail(
    db: DB,
    code: Annotated[
        str, Path(max_length=64, description="规格编码，来自规格列表的 code", examples=["gd_idcard"])
    ],
):
    return service.get_spec_detail(db, code)
