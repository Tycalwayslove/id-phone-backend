"""权益模块的返回模型。"""

from datetime import datetime

from pydantic import Field

from app.core.schemas import Schema


class EntitlementOut(Schema):
    """用户买到的一份权益，包含保管期、回执次数等。续费更新原权益的到期时间。"""

    id: int = Field(description="权益 ID", examples=[12])
    plan_code: str = Field(description="购买的套餐编码", examples=["photo_year_39_9"])
    plan_name: str = Field(description="购买的套餐名称，可直接展示", examples=["单张照片年度保管"])
    photo_id: int | None = Field(
        description="权益覆盖的照片 ID；为空表示覆盖该用户全部照片（如年度不限次套餐）", examples=[101]
    )
    starts_at: datetime = Field(description="权益生效时间（带时区）", examples=["2026-11-19T08:30:12Z"])
    ends_at: datetime = Field(
        description="权益到期时间（带时区），到期后不能下载和换规格", examples=["2027-11-19T08:30:12Z"]
    )
    is_active: bool = Field(
        description="当前是否有效：状态正常且还没到期为 true；已到期或被撤销为 false", examples=[True]
    )
    can_renew: bool = Field(
        description="权益是否符合续费条件。未撤销的独立权益在到期前或到期后 30 天内为 true，其他情况为 false",
        examples=[True],
    )
    spec_change: bool = Field(description="保管期内是否可以无限更换规格", examples=[True])
    one_person: bool = Field(
        description="是否一卡一人：true 时首次办理回执后只能给同一个人办", examples=[False]
    )
    receipt_quota_total: int = Field(description="可办回执总次数；套餐不含回执时为 0", examples=[1])
    receipt_quota_used: int = Field(description="已使用（含办理中占用）的回执次数", examples=[0])
    receipt_quota_left: int = Field(description="剩余回执次数 = 总次数 - 已使用", examples=[1])
    resubmit_limit: int = Field(description="回执被驳回后可免费重新提交的次数；没有则为 0", examples=[3])
