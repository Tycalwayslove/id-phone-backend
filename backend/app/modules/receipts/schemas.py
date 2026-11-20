"""回执模块的请求和返回模型。"""

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.core.schemas import Schema, page_model

ApplicationStatus = Literal["pending", "processing", "rejected", "completed", "failed", "cancelled"]
AttemptStatus = Literal[
    "created", "submitted", "unknown", "processing", "completed", "rejected", "failed", "abandoned"
]


class ReceiptProviderAck(Schema):
    """鹧应和黔微云收到此响应后，确认回调已处理。"""

    data: dict = Field(default_factory=dict, description="固定为空对象", examples=[{}])
    code: Literal[0] = Field(default=0, description="固定为 0，表示同步成功", examples=[0])
    msg: Literal["同步完成"] = Field(default="同步完成", description="固定为同步完成", examples=["同步完成"])


class ReceiptCreate(Schema):
    """创建回执申请的请求。"""

    photo_id: int = Field(description="要办理回执的照片 ID，必须是自己的照片", examples=[12])
    spec_code: str = Field(
        description="回执规格编码，来自规格列表；该规格必须支持办理回执",
        min_length=1,
        max_length=64,
        examples=["gd_idcard"],
    )
    form: dict[str, str] = Field(
        description=(
            "办理表单，key 来自规格详情里的 form_schema（如 name 姓名、idcard 身份证号、city 城市），"
            "value 是用户填写的文字。必填项不能为空；idcard 必须是 18 位，最后一位可以是 X"
        ),
        max_length=20,
        examples=[{"name": "张三", "idcard": "11010519491231002X", "city": "深圳市"}],
    )
    region_code: str | None = Field(
        default=None,
        description="办理地区的行政区划码，用于选择有该地区采集系统的通道；不限地区的规格不传",
        max_length=12,
        examples=["440300"],
    )


class ResubmitRequest(Schema):
    """驳回后重新提交的请求。"""

    photo_id: int | None = Field(
        default=None,
        description="换一张新照片重提时传入，必须是自己的照片；不传则沿用原来的照片重新提交",
        examples=[15],
    )


class SimulateRequest(Schema):
    """联调：模拟服务商给出办理结果。仅开发和测试环境可用。"""

    result: Literal["completed", "rejected", "failed"] = Field(
        description=(
            "要模拟的结果。completed = 办理成功并出回执；rejected = 被驳回；failed = 办理失败（通道故障等）"
        ),
        examples=["completed"],
    )
    reject_reason: str | None = Field(
        default=None,
        description="模拟驳回时的原因；只在 result 为 rejected 时有意义，不传用默认原因",
        max_length=200,
        examples=["照片不符合要求：背景不均匀"],
    )


class AttemptOut(Schema):
    """一次提交记录。驳回后每重提一次增加一条。"""

    seq: int = Field(description="第几次提交，从 1 开始", examples=[1])
    status: AttemptStatus = Field(
        description=(
            "这次提交的状态。created = 已创建还没发出；submitted = 已提交等待结果；"
            "unknown = 提交结果未知或需人工核对；processing = 对方办理中；"
            "completed = 已出回执；rejected = 被驳回；failed = 办理失败；abandoned = 已放弃"
        ),
        examples=["rejected"],
    )
    reject_reason: str | None = Field(
        default=None, description="被驳回的原因；没有被驳回时为空", examples=["照片不符合要求：背景不均匀"]
    )
    submitted_at: datetime | None = Field(
        default=None, description="提交成功的时间；还没提交成功时为空", examples=["2026-11-19T08:30:00Z"]
    )
    finished_at: datetime | None = Field(
        default=None, description="出结果的时间；还没出结果时为空", examples=["2026-11-19T09:10:00Z"]
    )


class ApplicationOut(Schema):
    """一条回执申请。"""

    app_no: str = Field(description="申请单号，对外唯一编号", examples=["R20261119083012A1B2C3"])
    status: ApplicationStatus = Field(
        description=(
            "申请状态。pending = 已创建，还没提交给服务商；processing = 办理中，等待结果；"
            "rejected = 被驳回，可以换照片重提（看 resubmit_left）；completed = 已出回执，可查看回执图片；"
            "failed = 办理失败，回执次数已退还；cancelled = 已取消，回执次数已退还"
        ),
        examples=["processing"],
    )
    spec_code: str = Field(description="规格编码", examples=["gd_idcard"])
    spec_name: str = Field(description="规格名称", examples=["广东省身份证"])
    photo_id: int = Field(description="当前使用的照片 ID；换照片重提后会变成新照片", examples=[12])
    entitlement_id: int = Field(description="本次占用回执次数的权益 ID", examples=[88])
    reject_reason: str | None = Field(
        default=None,
        description="驳回原因，展示给用户；只在 status 为 rejected 时有值",
        examples=["照片不符合要求：背景不均匀"],
    )
    rejected_at: datetime | None = Field(
        default=None,
        description="被驳回的时间；只在 status 为 rejected 时有值",
        examples=["2026-11-19T09:10:00Z"],
    )
    resubmit_count: int = Field(description="已经重新提交的次数，首次提交不算", examples=[1])
    resubmit_left: int = Field(
        description="还能重新提交几次，最小为 0；为 0 时被驳回后不能再重提", examples=[2]
    )
    image_code: str | None = Field(
        default=None,
        description="回执上的图像号，办理证件时使用；只在 completed 时有值",
        examples=["IMG1A2B3C4D"],
    )
    receipt_url: str | None = Field(
        default=None,
        description="已转存回执图片的临时链接，约 10 分钟有效。正在转存或未出回执时为空，过期后重新查询",
        examples=["https://api.example.com/files/..."],
    )
    official_expire_at: datetime | None = Field(
        default=None,
        description="官方回执的有效截止时间，过期后需要重新办理；未知或未出回执时为空",
        examples=["2027-02-17T00:00:00Z"],
    )
    completed_at: datetime | None = Field(
        default=None, description="出回执的时间；只在 completed 时有值", examples=["2026-11-19T09:10:00Z"]
    )
    created_at: datetime = Field(description="申请创建时间", examples=["2026-11-19T08:30:00Z"])
    form_masked: dict[str, str] = Field(
        description=(
            "打码后的办理表单，用于展示：姓名只显示姓加 *，身份证号只显示前 3 位和后 4 位，手机号中间打码，"
            "其他字段原样返回"
        ),
        examples=[{"name": "张*", "idcard": "110***********002X", "city": "深圳市"}],
    )
    attempts: list[AttemptOut] = Field(description="提交记录，按提交次序从早到晚")


ApplicationPage = page_model(ApplicationOut, "ApplicationPage")
