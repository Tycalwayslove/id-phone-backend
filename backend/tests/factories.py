"""测试数据工厂：在当前测试事务里造规格、套餐、服务商。各模块测试共用。"""

from sqlalchemy.orm import Session

from app.models import Plan, PlanBenefit, Provider, ProviderSpec, RouteRule, Spec


def make_spec(
    db: Session,
    code: str = "idcard_test",
    *,
    category: str = "receipt",
    width_px: int = 358,
    height_px: int = 441,
    bg_colors: list[str] | None = None,
    form_schema: list[dict] | None = None,
) -> Spec:
    spec = Spec(
        code=code,
        name=f"测试规格 {code}",
        category=category,
        cert_type="idcard",
        width_px=width_px,
        height_px=height_px,
        width_mm=26,
        height_mm=32,
        bg_colors=bg_colors or ["#FFFFFF", "#438EDB"],
        beauty_max=3,
        form_schema=form_schema
        or [
            {"key": "name", "label": "姓名", "required": True},
            {"key": "idcard", "label": "身份证号", "required": True},
        ],
        status="active",
    )
    db.add(spec)
    db.flush()
    return spec


def make_plan(
    db: Session, code: str, price_fen: int, benefits: dict[str, int], *, status: str = "on_sale"
) -> Plan:
    plan = Plan(code=code, name=f"测试套餐 {code}", price_fen=price_fen, status=status, display={})
    db.add(plan)
    db.flush()
    for k, v in benefits.items():
        db.add(PlanBenefit(plan_id=plan.id, benefit_type=k, int_value=v))
    db.flush()
    return plan


def make_provider_for(db: Session, spec: Spec, code: str = "fake_zheying") -> Provider:
    provider = Provider(
        code=code, name="测试通道", adapter="zheying", upstream_group="zheying", status="enabled"
    )
    db.add(provider)
    db.flush()
    db.add(ProviderSpec(provider_id=provider.id, spec_id=spec.id, provider_item_id="713", cost_fen=300))
    db.add(RouteRule(spec_id=spec.id, provider_id=provider.id, priority=10))
    db.flush()
    return provider


# 与 docs/product/requirements.md 的套餐一致
STANDARD_PLANS = {
    "single_19_9": (1990, {"storage_days": 30, "photo_scope": 1, "receipt_quota": 1, "resubmit_limit": 3}),
    "photo_year_39_9": (
        3990,
        {"storage_days": 365, "photo_scope": 1, "receipt_quota": 1, "resubmit_limit": 3, "spec_change": 1},
    ),
    "addon_receipt_10": (1000, {"receipt_quota": 1, "attach_to_parent": 1}),
    "unlimited_99": (
        9900,
        {
            "storage_days": 365,
            "photo_scope": 0,
            "receipt_quota": 10,
            "resubmit_limit": 3,
            "spec_change": 1,
            "one_person": 1,
        },
    ),
}


def make_standard_plans(db: Session) -> dict[str, Plan]:
    return {code: make_plan(db, code, price, b) for code, (price, b) in STANDARD_PLANS.items()}
