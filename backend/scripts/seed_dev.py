"""开发库演示数据：清空 idphone_dev 里的业务表，然后灌入一套能串起整条链路的数据。

运行（在 backend 目录下）：
    uv run python -m scripts.seed_dev

只允许在库名以 _dev 结尾的数据库上运行，防止误清生产数据。
数据里的手机号、身份证号都是假的，只为演示。
"""

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.models import (
    AdminUser,
    AuditLog,
    Base,
    Channel,
    Entitlement,
    EntitlementLedger,
    EntitlementQuota,
    File,
    NotifyTask,
    Order,
    OrderItem,
    Payment,
    Photo,
    PhotoRender,
    Plan,
    PlanBenefit,
    Provider,
    ProviderCallback,
    ProviderSpec,
    ReceiptApplication,
    ReceiptAttempt,
    RouteRule,
    ShareLink,
    Spec,
    User,
    UserIdentity,
    UserTag,
    WecomContact,
)

BUCKET = "idphone-dev"
ENV = "dev"
NOW = datetime.now(UTC)

# 套餐：price_fen 单位是分；benefits 是权益项
PLANS = [
    (
        "single_19_9",
        "单次精修 + 回执",
        1990,
        10,
        {"storage_days": 30, "photo_scope": 1, "receipt_quota": 1, "resubmit_limit": 3},
    ),
    (
        "photo_year_39_9",
        "单张照片年度保管",
        3990,
        20,
        {"storage_days": 365, "photo_scope": 1, "receipt_quota": 1, "resubmit_limit": 3, "spec_change": 1},
    ),
    ("addon_receipt_10", "加办一种回执", 1000, 30, {"receipt_quota": 1, "attach_to_parent": 1}),
    (
        "unlimited_99",
        "年度不限次",
        9900,
        40,
        {
            "storage_days": 365,
            "photo_scope": 0,
            "receipt_quota": 10,
            "resubmit_limit": 3,
            "spec_change": 1,
            "one_person": 1,
        },
    ),
]

FORM_MOBILE_CITY = [
    {"key": "mobile", "label": "手机号", "required": True},
    {"key": "city", "label": "办理城市", "required": True},
]
FORM_DRIVER = [
    *FORM_MOBILE_CITY,
    {"key": "name", "label": "姓名", "required": True},
    {"key": "idcard", "label": "身份证号", "required": True},
]

# 规格：(code, 名称, 类别, 证件类型, 区划码, 宽px, 高px, 宽mm, 高mm, 底色, 美化上限, 表单, 鹧应规格ID)
# 回执规格和对方规格 ID 来自鹧应公开的回执规格列表；普通规格没有对方 ID
SPECS = [
    (
        "gd-idcard",
        "广东身份证",
        "receipt",
        "id_card",
        "44",
        358,
        441,
        26,
        32,
        ["#FFFFFF"],
        2,
        FORM_MOBILE_CITY,
        "713",
    ),
    (
        "gz-idcard",
        "贵州身份证",
        "receipt",
        "id_card",
        "52",
        358,
        441,
        26,
        32,
        ["#FFFFFF"],
        2,
        [{"key": "mobile", "label": "手机号", "required": True}],
        "625",
    ),
    (
        "ah-idcard",
        "安徽身份证",
        "receipt",
        "id_card",
        "34",
        358,
        441,
        26,
        32,
        ["#FFFFFF"],
        2,
        [{"key": "mobile", "label": "手机号", "required": True}],
        "755",
    ),
    (
        "gd-driver",
        "广东驾驶证",
        "receipt",
        "driver",
        "44",
        413,
        579,
        35,
        49,
        ["#FFFFFF"],
        2,
        FORM_DRIVER,
        "622",
    ),
    (
        "gz-driver",
        "贵州驾驶证",
        "receipt",
        "driver",
        "52",
        413,
        579,
        35,
        49,
        ["#FFFFFF"],
        2,
        FORM_DRIVER,
        "736",
    ),
    (
        "gd-social",
        "广东社保卡",
        "receipt",
        "social",
        "44",
        358,
        441,
        26,
        32,
        ["#FFFFFF"],
        2,
        FORM_MOBILE_CITY,
        "712",
    ),
    (
        "gd-residence",
        "广东居住证",
        "receipt",
        "residence",
        "44",
        358,
        441,
        26,
        32,
        ["#FFFFFF"],
        2,
        FORM_MOBILE_CITY,
        "714",
    ),
    (
        "hk-macau-pass",
        "港澳通行证",
        "receipt",
        "hk_macau",
        None,
        390,
        567,
        33,
        48,
        ["#FFFFFF"],
        0,
        FORM_MOBILE_CITY,
        "624",
    ),
    (
        "one-inch",
        "一寸",
        "normal",
        "other",
        None,
        295,
        413,
        25,
        35,
        ["#438EDB", "#FFFFFF", "#FF0000"],
        4,
        [],
        None,
    ),
    (
        "two-inch",
        "二寸",
        "normal",
        "other",
        None,
        413,
        579,
        35,
        49,
        ["#438EDB", "#FFFFFF", "#FF0000"],
        4,
        [],
        None,
    ),
]


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def guard_dev_database() -> None:
    db_name = make_url(settings.database_url).database or ""
    if not db_name.endswith("_dev"):
        raise SystemExit(f"拒绝运行：当前数据库是 {db_name!r}，只允许 *_dev 库。")


def truncate_all() -> None:
    """清空所有业务表（保留 alembic_version），并把自增 ID 归零。"""
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


def add_file(db, user: User, kind: str, folder: str, suffix: str, ext: str, mime: str, size: int) -> File:
    """先插入拿到 id，再按命名规则生成 storage_key（末尾带文件 ID）。"""
    f = File(
        user_id=user.id,
        kind=kind,
        bucket=BUCKET,
        storage_key="pending",
        mime=mime,
        size_bytes=size,
        sha256=sha(f"{kind}{folder}{suffix}"),
    )
    db.add(f)
    db.flush()
    name = f"{kind}{suffix}_f{f.id}.{ext}"
    f.storage_key = f"{ENV}/u{user.id}/{folder}/{name}"
    db.flush()
    return f


def seed() -> None:
    with SessionLocal() as db:
        # ---------- 规格与供应链 ----------
        specs: dict[str, Spec] = {}
        for i, (code, name, cat, cert, region, wpx, hpx, wmm, hmm, colors, beauty, form, _) in enumerate(
            SPECS
        ):
            s = Spec(
                code=code,
                name=name,
                category=cat,
                cert_type=cert,
                region_code=region,
                width_px=wpx,
                height_px=hpx,
                width_mm=wmm,
                height_mm=hmm,
                bg_colors=colors,
                beauty_max=beauty,
                form_schema=form,
                official_valid_days=180 if cat == "receipt" else None,
                sort=i,
            )
            db.add(s)
            specs[code] = s
        db.flush()
        # 子规格示例：广东身份证 > 深圳市、广州市
        for code, name, region in [
            ("gd-idcard-sz", "广东身份证·深圳", "4403"),
            ("gd-idcard-gz", "广东身份证·广州", "4401"),
        ]:
            p = specs["gd-idcard"]
            child = Spec(
                code=code,
                name=name,
                parent_id=p.id,
                category="receipt",
                cert_type="id_card",
                region_code=region,
                width_px=p.width_px,
                height_px=p.height_px,
                width_mm=p.width_mm,
                height_mm=p.height_mm,
                bg_colors=["#FFFFFF"],
                beauty_max=2,
                form_schema=FORM_MOBILE_CITY,
                official_valid_days=180,
            )
            db.add(child)
            specs[code] = child

        zheying = Provider(code="zheying", name="鹧应证件照", adapter="zheying", upstream_group="zheying")
        qianweiyun = Provider(
            code="qianweiyun", name="黔微云证件照", adapter="qianweiyun", upstream_group="zheying"
        )
        clipimg = Provider(
            code="clipimg",
            name="可立图",
            adapter="clipimg",
            upstream_group="clipimg",
            status="disabled",
        )
        db.add_all([zheying, qianweiyun, clipimg])
        db.flush()

        for code, *_rest in SPECS:
            item_id = _rest[-1]
            if item_id is None:
                continue
            s = specs[code]
            for prov, priority in [(zheying, 10), (qianweiyun, 20)]:
                db.add(
                    ProviderSpec(
                        provider_id=prov.id,
                        spec_id=s.id,
                        provider_item_id=item_id,
                        cost_fen=700,
                        param_mapping={
                            "mobile": "text_mobile",
                            "city": "text_city",
                            "name": "text_name",
                            "idcard": "text_idcard",
                        },
                    )
                )
                db.add(RouteRule(spec_id=s.id, provider_id=prov.id, priority=priority))

        # ---------- 套餐 ----------
        plans: dict[str, Plan] = {}
        for code, name, price, sort, benefits in PLANS:
            p = Plan(
                code=code,
                name=name,
                price_fen=price,
                status="on_sale",
                sort=sort,
                display={"badge": "推荐"} if code == "photo_year_39_9" else {},
            )
            db.add(p)
            db.flush()
            for btype, val in benefits.items():
                db.add(PlanBenefit(plan_id=p.id, benefit_type=btype, int_value=val))
            plans[code] = p

        # ---------- 用户与私域 ----------
        xhs = Channel(code="xhs_note_01", name="小红书笔记·证件照避坑", source_type="xhs")
        dy = Channel(code="dy_video_01", name="抖音短视频·回执教程", source_type="douyin")
        expo = Channel(code="offline_pet_expo", name="宠物展快闪摊位", source_type="offline")
        db.add_all([xhs, dy, expo])
        db.flush()

        alice = User(
            nickname="演示用户-小林",
            phone_hash=sha("13800000001"),
            first_channel_id=xhs.id,
            last_active_at=NOW,
        )
        bob = User(
            nickname="演示用户-阿杰",
            phone_hash=sha("13800000002"),
            first_channel_id=dy.id,
            last_active_at=NOW - timedelta(days=2),
        )
        db.add_all([alice, bob])
        db.flush()

        db.add_all(
            [
                UserIdentity(
                    user_id=alice.id,
                    provider="wx_mini",
                    app_id="wx_demo_mini",
                    open_id="o_mini_alice",
                    union_id="u_alice",
                    subscribe_quota={"tmpl_receipt_result": 1},
                ),
                UserIdentity(
                    user_id=alice.id,
                    provider="wx_mp",
                    app_id="wx_demo_mp",
                    open_id="o_mp_alice",
                    union_id="u_alice",
                ),
                UserIdentity(
                    user_id=bob.id,
                    provider="wx_mini",
                    app_id="wx_demo_mini",
                    open_id="o_mini_bob",
                    union_id="u_bob",
                ),
                WecomContact(
                    user_id=alice.id,
                    external_userid="wm_ext_alice",
                    follow_userid="kefu_01",
                    state=f"u{alice.id}",
                    union_id="u_alice",
                    added_at=NOW - timedelta(days=9),
                ),
                UserTag(user_id=alice.id, tag_key="bought:photo_year", source="auto"),
                UserTag(user_id=alice.id, tag_key="receipt:gd-idcard", source="auto"),
                UserTag(user_id=bob.id, tag_key="intent:hk-macau-pass", source="manual"),
            ]
        )

        # ---------- 照片资产（小林拍了一张，重拍了一张）----------
        photos = []
        for _ in range(2):
            orig = add_file(db, alice, "original", "pending", "", "jpg", "image/jpeg", 2_400_000)
            mat = add_file(db, alice, "matting", "pending", "", "png", "image/png", 900_000)
            ph = Photo(
                user_id=alice.id,
                source="camera",
                original_file_id=orig.id,
                matting_file_id=mat.id,
                beauty_params={"level": 1},
                check_result={"passed": True},
                access_until=NOW + timedelta(days=355),
                retain_until=NOW + timedelta(days=535),
                status="active",
            )
            db.add(ph)
            db.flush()
            # 照片 ID 有了，把文件挪到 p{照片ID} 目录下（命名规则里文件夹用照片 ID）
            for f in (orig, mat):
                f.storage_key = f.storage_key.replace("/pending/", f"/p{ph.id}/")
            photos.append(ph)
        photo_v1, photo_v2 = photos

        def render(photo: Photo, spec_code: str, color: str, beauty: int, watermarked: bool) -> PhotoRender:
            kind = "preview" if watermarked else "render"
            f = add_file(
                db,
                alice,
                kind,
                f"p{photo.id}",
                f"_{spec_code}_{color.removeprefix('#')}_b{beauty}",
                "jpg",
                "image/jpeg",
                60_000,
            )
            r = PhotoRender(
                photo_id=photo.id,
                spec_id=specs[spec_code].id,
                file_id=f.id,
                bg_color=color,
                beauty_level=beauty,
                watermarked=watermarked,
            )
            db.add(r)
            db.flush()
            return r

        render(photo_v1, "gd-idcard", "#FFFFFF", 2, True)  # 付费前的带水印预览
        r_v1 = render(photo_v1, "gd-idcard", "#FFFFFF", 2, False)  # 第一次提交用的
        r_v2 = render(photo_v2, "gd-idcard", "#FFFFFF", 1, False)  # 驳回后重拍、降低美化
        r_inch = render(photo_v2, "one-inch", "#438EDB", 1, False)  # 同一底片改规格
        db.add(
            ShareLink(
                render_id=r_inch.id,
                token="share_demo_token_01",
                expires_at=NOW + timedelta(days=7),
                max_downloads=5,
            )
        )

        # ---------- 交易与权益：小林买了 39.9 年度单照 ----------
        plan = plans["photo_year_39_9"]
        benefits = PLANS[1][4]
        order = Order(
            order_no="O20261118000001",
            user_id=alice.id,
            channel_id=xhs.id,
            total_fen=plan.price_fen,
            paid_fen=plan.price_fen,
            status="paid",
            client="wx_mini",
            paid_at=NOW - timedelta(days=10),
            expire_at=NOW - timedelta(days=10) + timedelta(minutes=30),
        )
        db.add(order)
        db.flush()
        item = OrderItem(
            order_id=order.id,
            item_type="plan",
            plan_id=plan.id,
            photo_id=photo_v1.id,
            unit_price_fen=plan.price_fen,
            amount_fen=plan.price_fen,
            snapshot={"plan_code": plan.code, "benefits": benefits},
        )
        db.add(item)
        db.add(
            Payment(
                order_id=order.id,
                channel="wxpay",
                out_trade_no="P20261118000001",
                transaction_id="4200000000202611180000001",
                amount_fen=plan.price_fen,
                status="success",
                paid_at=NOW - timedelta(days=10),
                raw={"trade_state": "SUCCESS"},
            )
        )
        db.flush()
        ent = Entitlement(
            user_id=alice.id,
            order_item_id=item.id,
            plan_id=plan.id,
            photo_id=photo_v1.id,
            starts_at=NOW - timedelta(days=10),
            ends_at=NOW + timedelta(days=355),
            benefits_snapshot=benefits,
        )
        db.add(ent)
        db.flush()
        quota = EntitlementQuota(entitlement_id=ent.id, benefit_type="receipt_quota", total=1, used=1)
        db.add(quota)

        # 阿杰下了一个 99 元的单但还没付款
        pending = Order(
            order_no="O20261118000002",
            user_id=bob.id,
            channel_id=dy.id,
            total_fen=9900,
            status="pending",
            client="wx_mini",
            expire_at=NOW + timedelta(minutes=25),
        )
        db.add(pending)
        db.flush()
        db.add(
            OrderItem(
                order_id=pending.id,
                item_type="plan",
                plan_id=plans["unlimited_99"].id,
                unit_price_fen=9900,
                amount_fen=9900,
                snapshot={"plan_code": "unlimited_99"},
            )
        )
        db.flush()

        # ---------- 回执履约：第一次被驳回，换照片重提后出证 ----------
        receipt_file = add_file(db, alice, "receipt", "pending", "", "pdf", "application/pdf", 120_000)
        app = ReceiptApplication(
            app_no="R20261118000001",
            user_id=alice.id,
            photo_id=photo_v2.id,
            spec_id=specs["gd-idcard-sz"].id,
            entitlement_id=ent.id,
            region_code="4403",
            idcard_hash=sha("TEST-IDCARD-0001"),
            status="completed",
            resubmit_count=1,
            reject_reason="背景不均匀，请在纯色背景前重拍",
            rejected_at=NOW - timedelta(days=9, hours=20),
            image_code="DEMO-IMG-0001",
            receipt_file_id=receipt_file.id,
            official_expire_at=NOW + timedelta(days=171),
            completed_at=NOW - timedelta(days=9),
        )
        db.add(app)
        db.flush()
        receipt_file.storage_key = receipt_file.storage_key.replace("/pending/", f"/a{app.id}/")
        ent.bound_idcard_hash = app.idcard_hash  # 一卡一人：首次办理时绑定

        att1 = ReceiptAttempt(
            application_id=app.id,
            seq=1,
            provider_id=zheying.id,
            render_id=r_v1.id,
            provider_order_no="ZY-DEMO-1001",
            is_current=False,
            status="rejected",
            reject_reason="背景不均匀",
            request_payload={"item_id": "713", "text_city": "深圳市"},
            submitted_at=NOW - timedelta(days=10),
            finished_at=NOW - timedelta(days=9, hours=20),
        )
        db.add(att1)
        db.flush()  # 先把第一条的 is_current 落库，再插第二条，避免撞“只能有一条当前提交”
        att2 = ReceiptAttempt(
            application_id=app.id,
            seq=2,
            provider_id=zheying.id,
            render_id=r_v2.id,
            provider_order_no="ZY-DEMO-1002",
            is_current=True,
            status="completed",
            cost_fen=700,
            request_payload={"item_id": "713", "text_city": "深圳市"},
            submitted_at=NOW - timedelta(days=9, hours=12),
            finished_at=NOW - timedelta(days=9),
        )
        db.add(att2)
        db.flush()

        db.add_all(
            [
                EntitlementLedger(quota_id=quota.id, application_id=app.id, action="reserve", delta=1),
                EntitlementLedger(quota_id=quota.id, application_id=app.id, action="confirm", delta=0),
                ProviderCallback(
                    provider_id=zheying.id,
                    attempt_id=att1.id,
                    provider_order_no="ZY-DEMO-1001",
                    event_status="-1",
                    payload={"order_no": "ZY-DEMO-1001", "status": -1, "msg": "背景不均匀"},
                    signature_ok=True,
                    dedupe_key="zheying:ZY-DEMO-1001:-1",
                    process_result="applied",
                    received_at=NOW - timedelta(days=9, hours=20),
                    processed_at=NOW - timedelta(days=9, hours=20),
                ),
                ProviderCallback(
                    provider_id=zheying.id,
                    attempt_id=att2.id,
                    provider_order_no="ZY-DEMO-1002",
                    event_status="4",
                    payload={"order_no": "ZY-DEMO-1002", "status": 4},
                    signature_ok=True,
                    dedupe_key="zheying:ZY-DEMO-1002:4",
                    process_result="applied",
                    received_at=NOW - timedelta(days=9),
                    processed_at=NOW - timedelta(days=9),
                ),
                # 同一个回调又来了一次：被识别为重复
                ProviderCallback(
                    provider_id=zheying.id,
                    attempt_id=att2.id,
                    provider_order_no="ZY-DEMO-1002",
                    event_status="4",
                    payload={"order_no": "ZY-DEMO-1002", "status": 4},
                    signature_ok=True,
                    dedupe_key="zheying:ZY-DEMO-1002:4:retry",
                    process_result="duplicate",
                    received_at=NOW - timedelta(days=9) + timedelta(minutes=1),
                    processed_at=NOW - timedelta(days=9) + timedelta(minutes=1),
                ),
            ]
        )

        # ---------- 通知：驳回升级 + 出证 + 到期提醒 ----------
        rej_at = NOW - timedelta(days=9, hours=20)
        db.add_all(
            [
                NotifyTask(
                    user_id=alice.id,
                    application_id=app.id,
                    event="receipt_rejected",
                    step=1,
                    channel="mini_subscribe",
                    scheduled_at=rej_at,
                    sent_at=rej_at,
                    status="sent",
                ),
                NotifyTask(
                    user_id=alice.id,
                    application_id=app.id,
                    event="receipt_rejected",
                    step=1,
                    channel="mp_template",
                    scheduled_at=rej_at,
                    sent_at=rej_at,
                    status="sent",
                ),
                NotifyTask(
                    user_id=alice.id,
                    application_id=app.id,
                    event="receipt_rejected",
                    step=2,
                    channel="wecom",
                    scheduled_at=rej_at + timedelta(hours=2),
                    status="cancelled",
                    result={"reason": "用户已重提"},
                ),
                NotifyTask(
                    user_id=alice.id,
                    application_id=app.id,
                    event="receipt_completed",
                    step=1,
                    channel="mini_subscribe",
                    scheduled_at=NOW - timedelta(days=9),
                    sent_at=NOW - timedelta(days=9),
                    status="sent",
                ),
                NotifyTask(
                    user_id=alice.id,
                    entitlement_id=ent.id,
                    event="entitlement_expiring",
                    step=1,
                    channel="mini_subscribe",
                    scheduled_at=ent.ends_at - timedelta(days=7),
                ),
            ]
        )

        # ---------- 后台 ----------
        admin = AdminUser(username="admin", password_hash="dev-only-not-a-real-hash", role="owner")
        db.add(admin)
        db.flush()
        db.add(
            AuditLog(
                admin_id=admin.id,
                action="view_application",
                target_type="receipt_application",
                target_id=app.id,
            )
        )

        db.commit()


def main() -> None:
    guard_dev_database()
    truncate_all()
    seed()
    with engine.connect() as conn:
        rows = []
        for t in Base.metadata.sorted_tables:
            n = conn.execute(text(f"SELECT count(*) FROM {t.name}")).scalar_one()
            rows.append((t.name, n))
    print("\n演示数据已写入：")
    for name, n in rows:
        print(f"  {name:<22} {n}")


if __name__ == "__main__":
    main()
