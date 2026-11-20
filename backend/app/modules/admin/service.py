"""运营后台业务：登录会话、查询、退款、套餐/规格/服务商配置、审计。

事务：写操作在这里 commit，并且审计日志和业务改动在同一个事务里提交。
列表/详情直接读各业务表（见 repo.py）；写操作尽量调用对应模块的 service。
审计日志的 before/after 只放关键字段，不放手机号、身份证号。
"""

import json
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import settings
from app.core.deps import ALL_PERMISSIONS, ROLE_PERMISSIONS, CurrentAdmin, PageParams, csrf_for
from app.core.errors import AppError, ErrorCode
from app.core.schemas import OkResponse
from app.core.utils import decode_cursor, encode_cursor, utcnow
from app.models import (
    AdminSession,
    AuditLog,
    Order,
    OrderItem,
    Plan,
    PlanBenefit,
    ReceiptApplication,
    Spec,
    User,
)
from app.models.trade import BENEFIT_TYPES
from app.modules.admin import repo
from app.modules.admin.schemas import (
    AdminApplicationDetail,
    AdminApplicationOut,
    AdminApplicationPage,
    AdminAttemptOut,
    AdminAuditLogOut,
    AdminAuditLogPage,
    AdminBriefOut,
    AdminLoginOut,
    AdminMeOut,
    AdminOrderDetail,
    AdminOrderOut,
    AdminOrderPage,
    AdminPaymentOut,
    AdminPlanCreateIn,
    AdminPlanOut,
    AdminPlanUpdateIn,
    AdminProviderOut,
    AdminProviderSpecOut,
    AdminProviderUpdateIn,
    AdminRefundIn,
    AdminRefundOut,
    AdminRefundResultOut,
    AdminRouteRuleOut,
    AdminSpecCreateIn,
    AdminSpecOut,
    AdminSpecPage,
    AdminSpecUpdateIn,
    AdminUserDetail,
    AdminUserOut,
    AdminUserPage,
)
from app.modules.orders import service as order_service
from app.modules.orders.schemas import OrderItemOut
from app.modules.receipts import service as receipt_service

# ---------- 登录失败限流 ----------
# 单进程内存实现：同一 username 在窗口内失败达到上限就拒绝登录。
# 多实例部署（多个 uvicorn worker / 多台服务器）时各进程各记各的，上限会被放大，
# 那时必须换成 Redis（INCR + EXPIRE）。
LOGIN_FAIL_LIMIT = 5
LOGIN_FAIL_WINDOW = 15 * 60  # 秒
_fails: dict[str, list[float]] = {}
_fails_lock = threading.Lock()
_FAILS_MAX_KEYS = 10_000


def _recent_fails(key: str, now: float) -> list[float]:
    recent = [t for t in _fails.get(key, []) if now - t < LOGIN_FAIL_WINDOW]
    if recent:
        _fails[key] = recent
    else:
        _fails.pop(key, None)
    return recent


def _check_rate(key: str) -> None:
    with _fails_lock:
        if len(_recent_fails(key, time.monotonic())) >= LOGIN_FAIL_LIMIT:
            raise AppError(ErrorCode.RATE_LIMITED)


def _record_fail(key: str) -> None:
    now = time.monotonic()
    with _fails_lock:
        if len(_fails) >= _FAILS_MAX_KEYS:  # 防止被随机用户名撑爆内存：清掉已过期的
            for k in list(_fails):
                _recent_fails(k, now)
        _fails.setdefault(key, []).append(now)


def _clear_fails(key: str) -> None:
    with _fails_lock:
        _fails.pop(key, None)


def reset_login_limiter() -> None:
    """测试用：清空失败记录。"""
    with _fails_lock:
        _fails.clear()


_dummy_hash: str | None = None


def _burn_password_check(password: str) -> None:
    """账号不存在时也做一次哈希校验，让响应时间和“密码错”接近，避免枚举用户名。"""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = security.hash_password("dummy-password-for-timing")
    security.verify_password(_dummy_hash, password)


# ---------- 审计 ----------


def _audit(
    db: Session,
    admin_id: int,
    action: str,
    target_type: str,
    target_id: int | None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            admin_id=admin_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            before=before,
            after=after,
        )
    )


def _j(value: Any) -> Any:
    """转成能存进 JSONB 的值。"""
    return value.isoformat() if isinstance(value, datetime) else value


# ---------- 分页 ----------


def _before_id(cursor: str | None) -> int | None:
    cur = decode_cursor(cursor)
    value = cur.get("i") if cur else None
    return value if isinstance(value, int) else None


def _slice[T](rows: list[T], limit: int) -> tuple[list[T], bool]:
    return rows[:limit], len(rows) > limit


def _next(rows: list, has_more: bool) -> str | None:
    return encode_cursor({"i": rows[-1].id}) if has_more and rows else None


# ---------- 登录 / 退出 / 我 ----------


def login(
    db: Session, *, username: str, password: str, user_agent: str | None, ip: str | None
) -> tuple[AdminLoginOut, str]:
    """校验账号密码，建会话。返回 (响应体, 明文令牌)，令牌由 router 写进 Cookie。"""
    key = username.strip().lower()
    _check_rate(key)
    admin = repo.get_admin_by_username(db, username)
    if admin is None:
        _burn_password_check(password)
        ok = False
    else:
        ok = security.verify_password(admin.password_hash, password) and admin.status == "active"
    if not ok or admin is None:
        _record_fail(key)
        raise AppError(ErrorCode.ADMIN_LOGIN_FAILED)
    _clear_fails(key)

    now = utcnow()
    token = security.new_token()
    token_hash = security.hash_token(token)
    session = AdminSession(
        admin_id=admin.id,
        token_hash=token_hash,
        user_agent=user_agent[:500] if user_agent else None,
        ip=ip,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.admin_session_idle_hours),
        absolute_expires_at=now + timedelta(hours=settings.admin_session_absolute_hours),
    )
    db.add(session)
    db.flush()
    _audit(db, admin.id, "auth.login", "admin_session", session.id)
    db.commit()
    out = AdminLoginOut(
        csrf_token=csrf_for(token_hash),
        admin=AdminBriefOut(id=admin.id, username=admin.username, role=admin.role),  # type: ignore[arg-type]
    )
    return out, token


def logout(db: Session, *, token: str | None) -> OkResponse:
    """吊销令牌对应的会话。没带令牌、令牌无效、已吊销都当成功（幂等）。"""
    if token:
        session = repo.get_session_by_hash(db, security.hash_token(token))
        if session is not None and session.revoked_at is None:
            session.revoked_at = utcnow()
            _audit(db, session.admin_id, "auth.logout", "admin_session", session.id)
            db.commit()
    return OkResponse()


def all_permissions() -> list[str]:
    return sorted(ALL_PERMISSIONS)


def me(admin: CurrentAdmin) -> AdminMeOut:
    granted = ROLE_PERMISSIONS.get(admin.role, set())
    perms = all_permissions() if "*" in granted else sorted(granted)
    return AdminMeOut(id=admin.id, username=admin.username, role=admin.role, permissions=perms)  # type: ignore[arg-type]


# ---------- 用户 ----------


def _phone_masked(user: User) -> str | None:
    if not user.phone_enc:
        return None
    return security.mask_phone(security.decrypt(user.phone_enc, "phone"))


def _user_outs(db: Session, users: list[User]) -> list[dict]:
    ids = [u.id for u in users]
    stats = repo.user_order_stats(db, ids)
    idents = repo.identity_providers(db, ids)
    return [
        dict(
            id=u.id,
            nickname=u.nickname,
            phone_masked=_phone_masked(u),
            status=u.status,
            created_at=u.created_at,
            last_active_at=u.last_active_at,
            identities=idents[u.id],
            orders_count=stats.get(u.id, (0, 0))[0],
            paid_fen_total=stats.get(u.id, (0, 0))[1],
        )
        for u in users
    ]


def list_users(
    db: Session, *, user_id: int | None, status: str | None, page: PageParams, phone: str | None = None
) -> AdminUserPage:
    phone_hash = security.keyed_hash(phone.strip(), "phone") if phone else None
    rows = repo.list_users(
        db,
        user_id=user_id,
        phone_hash=phone_hash,
        status=status,
        before_id=_before_id(page.cursor),
        limit=page.limit + 1,
    )
    rows, more = _slice(rows, page.limit)
    return AdminUserPage(
        items=[AdminUserOut(**d) for d in _user_outs(db, rows)], next_cursor=_next(rows, more)
    )


def get_user(db: Session, user_id: int) -> AdminUserDetail:
    user = repo.get_user(db, user_id)
    if user is None:
        raise AppError(ErrorCode.NOT_FOUND, "用户不存在")
    return AdminUserDetail(
        **_user_outs(db, [user])[0],
        avatar_url=user.avatar_url,
        applications_count=repo.applications_count(db, user.id),
    )


# ---------- 订单 ----------


def _order_fields(order: Order, items: list[OrderItem]) -> dict:
    return dict(
        order_no=order.order_no,
        user_id=order.user_id,
        status=order.status,
        total_fen=order.total_fen,
        paid_fen=order.paid_fen,
        refunded_fen=order.refunded_fen,
        created_at=order.created_at,
        paid_at=order.paid_at,
        items=[
            OrderItemOut(
                item_type=it.item_type,  # type: ignore[arg-type]
                plan_code=(it.snapshot or {}).get("plan_code"),
                plan_name=(it.snapshot or {}).get("plan_name"),
                photo_id=it.photo_id,
                amount_fen=it.amount_fen,
            )
            for it in items
        ],
    )


def _refund_out(r) -> AdminRefundOut:
    return AdminRefundOut(
        out_refund_no=r.out_refund_no,
        amount_fen=r.amount_fen,
        reason=r.reason,
        status=r.status,
        operator=r.operator,
        created_at=r.created_at,
        finished_at=r.finished_at,
    )


def list_orders(
    db: Session,
    *,
    status: str | None,
    order_no: str | None,
    user_id: int | None,
    created_from: datetime | None,
    created_to: datetime | None,
    page: PageParams,
) -> AdminOrderPage:
    rows = repo.list_orders(
        db,
        status=status,
        order_no=order_no,
        user_id=user_id,
        created_from=created_from,
        created_to=created_to,
        before_id=_before_id(page.cursor),
        limit=page.limit + 1,
    )
    rows, more = _slice(rows, page.limit)
    items = repo.items_by_order(db, [o.id for o in rows])
    return AdminOrderPage(
        items=[AdminOrderOut(**_order_fields(o, items[o.id])) for o in rows], next_cursor=_next(rows, more)
    )


def get_order(db: Session, order_no: str) -> AdminOrderDetail:
    order = repo.get_order_by_no(db, order_no)
    if order is None:
        raise AppError(ErrorCode.ORDER_NOT_FOUND)
    items = repo.items_by_order(db, [order.id])[order.id]
    return AdminOrderDetail(
        **_order_fields(order, items),
        payments=[
            AdminPaymentOut(
                channel=p.channel,
                out_trade_no=p.out_trade_no,
                transaction_id=p.transaction_id,
                amount_fen=p.amount_fen,
                status=p.status,  # type: ignore[arg-type]
                paid_at=p.paid_at,
            )
            for p in repo.payments_of(db, order.id)
        ],
        refunds=[_refund_out(r) for r in repo.refunds_of(db, order.id)],
    )


def refund_order(
    db: Session, admin: CurrentAdmin, order_no: str, body: AdminRefundIn
) -> AdminRefundResultOut:
    try:
        result = order_service.refund_order(
            db,
            order_no=order_no,
            request_id=body.request_id,
            amount_fen=body.amount_fen,
            reason=body.reason,
            operator=admin.username,
        )
        refund, order = result.refund, result.order
        if result.before is not None:
            _audit(
                db,
                admin.id,
                "refund.create",
                "order",
                order.id,
                result.before,
                {
                    "status": order.status,
                    "refunded_fen": order.refunded_fen,
                    "out_refund_no": refund.out_refund_no,
                    "refund_status": refund.status,
                    "amount_fen": refund.amount_fen,
                },
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return AdminRefundResultOut(
        **_refund_out(refund).model_dump(),
        order_no=order.order_no,
        order_status=order.status,  # type: ignore[arg-type]
        order_refunded_fen=order.refunded_fen,
    )


# ---------- 回执申请 ----------


def _application_fields(app: ReceiptApplication, spec: Spec) -> dict:
    return dict(
        app_no=app.app_no,
        user_id=app.user_id,
        status=app.status,
        spec_code=spec.code,
        spec_name=spec.name,
        photo_id=app.photo_id,
        entitlement_id=app.entitlement_id,
        resubmit_count=app.resubmit_count,
        reject_reason=app.reject_reason,
        created_at=app.created_at,
        updated_at=app.updated_at,
        completed_at=app.completed_at,
    )


def list_applications(
    db: Session,
    *,
    status: str | None,
    app_no: str | None,
    user_id: int | None,
    spec_code: str | None,
    page: PageParams,
) -> AdminApplicationPage:
    rows = repo.list_applications(
        db,
        status=status,
        app_no=app_no,
        user_id=user_id,
        spec_code=spec_code,
        before_id=_before_id(page.cursor),
        limit=page.limit + 1,
    )
    rows, more = _slice(rows, page.limit)
    specs = repo.specs_by_ids(db, (a.spec_id for a in rows))
    return AdminApplicationPage(
        items=[AdminApplicationOut(**_application_fields(a, specs[a.spec_id])) for a in rows],
        next_cursor=_next(rows, more),
    )


def _application_detail(db: Session, app: ReceiptApplication) -> AdminApplicationDetail:
    spec = repo.specs_by_ids(db, [app.spec_id])[app.spec_id]
    attempts = repo.attempts_by_app(db, [app.id])[app.id]
    form = json.loads(security.decrypt(app.form_data_enc, "receipt_form")) if app.form_data_enc else {}
    return AdminApplicationDetail(
        **_application_fields(app, spec),
        region_code=app.region_code,
        image_code=app.image_code,
        rejected_at=app.rejected_at,
        official_expire_at=app.official_expire_at,
        form_masked=receipt_service.mask_form(form),
        attempts=[
            AdminAttemptOut(
                seq=a.seq,
                provider_code=code,
                status=a.status,  # type: ignore[arg-type]
                is_current=a.is_current,
                reject_reason=a.reject_reason,
                cost_fen=a.cost_fen,
                submitted_at=a.submitted_at,
                finished_at=a.finished_at,
            )
            for a, code in attempts
        ],
    )


def get_application(db: Session, app_no: str) -> AdminApplicationDetail:
    app = repo.get_application_by_no(db, app_no)
    if app is None:
        raise AppError(ErrorCode.APPLICATION_NOT_FOUND)
    return _application_detail(db, app)


def cancel_application(db: Session, admin: CurrentAdmin, app_no: str) -> AdminApplicationDetail:
    app = repo.get_application_by_no(db, app_no)
    if app is None:
        raise AppError(ErrorCode.APPLICATION_NOT_FOUND)
    before = {"status": app.status}
    _audit(db, admin.id, "application.cancel", "receipt_application", app.id, before, {"status": "cancelled"})
    try:
        app = receipt_service.cancel_application(db, user_id=app.user_id, app_no=app_no)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _application_detail(db, app)


# ---------- 套餐 ----------

_PLAN_NON_NULL = {"name", "price_fen", "status", "sort", "display"}


def _check_benefits(benefits: dict[str, int]) -> None:
    for k, v in benefits.items():
        if k not in BENEFIT_TYPES:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"不支持的权益类型：{k}")
        if v < 0 or v > 100_000:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"权益 {k} 的值必须在 0～100000 之间")


def _check_window(starts: datetime | None, ends: datetime | None) -> None:
    if starts is not None and ends is not None and ends <= starts:
        raise AppError(ErrorCode.VALIDATION_ERROR, "停售时间必须晚于开售时间")


def _plan_out(plan: Plan, benefits: dict[str, int]) -> AdminPlanOut:
    return AdminPlanOut(
        code=plan.code,
        name=plan.name,
        price_fen=plan.price_fen,
        status=plan.status,  # type: ignore[arg-type]
        sort=plan.sort,
        sale_starts_at=plan.sale_starts_at,
        sale_ends_at=plan.sale_ends_at,
        display=plan.display or {},
        benefits=benefits,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def _plan_snapshot(plan: Plan, benefits: dict[str, int]) -> dict:
    return {
        "code": plan.code,
        "name": plan.name,
        "price_fen": plan.price_fen,
        "status": plan.status,
        "sort": plan.sort,
        "sale_starts_at": _j(plan.sale_starts_at),
        "sale_ends_at": _j(plan.sale_ends_at),
        "display": plan.display,
        "benefits": benefits,
    }


def list_plans(db: Session) -> list[AdminPlanOut]:
    plans = repo.list_plans(db)
    rows = repo.benefit_rows(db, [p.id for p in plans])
    return [_plan_out(p, {b.benefit_type: b.int_value for b in rows[p.id]}) for p in plans]


def create_plan(db: Session, admin: CurrentAdmin, body: AdminPlanCreateIn) -> AdminPlanOut:
    _check_benefits(body.benefits)
    _check_window(body.sale_starts_at, body.sale_ends_at)
    if repo.get_plan_by_code(db, body.code) is not None:
        raise AppError(ErrorCode.CONFLICT)
    plan = Plan(
        code=body.code,
        name=body.name,
        price_fen=body.price_fen,
        status=body.status,
        sort=body.sort,
        sale_starts_at=body.sale_starts_at,
        sale_ends_at=body.sale_ends_at,
        display=body.display,
    )
    db.add(plan)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        if isinstance(e.orig, UniqueViolation) and e.orig.diag.constraint_name == "uq_plans_code":
            raise AppError(ErrorCode.CONFLICT) from e
        raise
    db.add_all(PlanBenefit(plan_id=plan.id, benefit_type=k, int_value=v) for k, v in body.benefits.items())
    db.flush()
    db.refresh(plan)
    _audit(db, admin.id, "plan.create", "plan", plan.id, None, _plan_snapshot(plan, body.benefits))
    db.commit()
    return _plan_out(plan, dict(body.benefits))


def update_plan(db: Session, admin: CurrentAdmin, code: str, body: AdminPlanUpdateIn) -> AdminPlanOut:
    plan = repo.get_plan_by_code(db, code, for_update=True)
    if plan is None:
        raise AppError(ErrorCode.NOT_FOUND, "套餐不存在")
    data = body.model_dump(exclude_unset=True)
    new_benefits = data.pop("benefits", None)
    old_rows = {b.benefit_type: b for b in repo.benefit_rows(db, [plan.id])[plan.id]}
    old_benefits = {k: b.int_value for k, b in old_rows.items()}

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for k, v in data.items():
        if v is None and k in _PLAN_NON_NULL:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"{k} 不能为空")
        old = getattr(plan, k)
        if old != v:
            before[k], after[k] = _j(old), _j(v)
            setattr(plan, k, v)
    _check_window(plan.sale_starts_at, plan.sale_ends_at)

    if new_benefits is not None:
        _check_benefits(new_benefits)
        if new_benefits != old_benefits:
            before["benefits"], after["benefits"] = old_benefits, new_benefits
            # 按差异改，避免“先插后删”撞唯一约束
            for k, row in old_rows.items():
                if k not in new_benefits:
                    db.delete(row)
            for k, v in new_benefits.items():
                if k in old_rows:
                    old_rows[k].int_value = v
                else:
                    db.add(PlanBenefit(plan_id=plan.id, benefit_type=k, int_value=v))
    if after:
        db.flush()
        _audit(db, admin.id, "plan.update", "plan", plan.id, before, after)
        db.commit()
        db.refresh(plan)
    final = new_benefits if new_benefits is not None else old_benefits
    return _plan_out(plan, dict(final))


# ---------- 规格 ----------

_SPEC_NULLABLE = {
    "region_code",
    "width_mm",
    "height_mm",
    "file_size_min_kb",
    "file_size_max_kb",
    "official_valid_days",
}


def _check_file_size(lo: int | None, hi: int | None) -> None:
    if lo is not None and hi is not None and lo > hi:
        raise AppError(ErrorCode.VALIDATION_ERROR, "文件大小下限不能大于上限")


def _spec_out(spec: Spec, parent_code: str | None) -> AdminSpecOut:
    return AdminSpecOut(
        code=spec.code,
        name=spec.name,
        parent_code=parent_code,
        category=spec.category,  # type: ignore[arg-type]
        cert_type=spec.cert_type,
        region_code=spec.region_code,
        width_px=spec.width_px,
        height_px=spec.height_px,
        width_mm=spec.width_mm,
        height_mm=spec.height_mm,
        dpi=spec.dpi,
        bg_colors=spec.bg_colors,
        file_size_min_kb=spec.file_size_min_kb,
        file_size_max_kb=spec.file_size_max_kb,
        beauty_max=spec.beauty_max,
        form_schema=spec.form_schema,  # type: ignore[arg-type]
        official_valid_days=spec.official_valid_days,
        status=spec.status,  # type: ignore[arg-type]
        sort=spec.sort,
        created_at=spec.created_at,
        updated_at=spec.updated_at,
    )


def list_specs(db: Session, page: PageParams) -> AdminSpecPage:
    rows = repo.list_specs(db, before_id=_before_id(page.cursor), limit=page.limit + 1)
    rows, more = _slice(rows, page.limit)
    codes = repo.spec_codes(db, (s.parent_id for s in rows if s.parent_id))
    return AdminSpecPage(
        items=[_spec_out(s, codes.get(s.parent_id) if s.parent_id else None) for s in rows],
        next_cursor=_next(rows, more),
    )


def create_spec(db: Session, admin: CurrentAdmin, body: AdminSpecCreateIn) -> AdminSpecOut:
    _check_file_size(body.file_size_min_kb, body.file_size_max_kb)
    if repo.get_spec_by_code(db, body.code) is not None:
        raise AppError(ErrorCode.CONFLICT)
    parent = None
    if body.parent_code:
        parent = repo.get_spec_by_code(db, body.parent_code)
        if parent is None:
            raise AppError(ErrorCode.VALIDATION_ERROR, "父规格不存在")
    data = body.model_dump(exclude={"parent_code"})
    spec = Spec(**data, parent_id=parent.id if parent else None)
    db.add(spec)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        if isinstance(e.orig, UniqueViolation) and e.orig.diag.constraint_name == "uq_specs_code":
            raise AppError(ErrorCode.CONFLICT) from e
        raise
    db.refresh(spec)
    _audit(
        db,
        admin.id,
        "spec.create",
        "spec",
        spec.id,
        None,
        {"code": spec.code, "name": spec.name, "category": spec.category, "status": spec.status},
    )
    db.commit()
    return _spec_out(spec, parent.code if parent else None)


def update_spec(db: Session, admin: CurrentAdmin, code: str, body: AdminSpecUpdateIn) -> AdminSpecOut:
    spec = repo.get_spec_by_code(db, code, for_update=True)
    if spec is None:
        raise AppError(ErrorCode.NOT_FOUND, "规格不存在")
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is None and k not in _SPEC_NULLABLE:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"{k} 不能为空")
        old = getattr(spec, k)
        if old != v:
            before[k], after[k] = old, v
            setattr(spec, k, v)
    _check_file_size(spec.file_size_min_kb, spec.file_size_max_kb)
    if after:
        db.flush()
        _audit(db, admin.id, "spec.update", "spec", spec.id, before, after)
        db.commit()
        db.refresh(spec)
    parent_code = repo.spec_codes(db, [spec.parent_id]).get(spec.parent_id) if spec.parent_id else None
    return _spec_out(spec, parent_code)


# ---------- 服务商 ----------


def list_providers(db: Session) -> list[AdminProviderOut]:
    providers = repo.list_providers(db)
    pspecs = repo.provider_specs(db)
    rules = repo.route_rules(db)
    codes = repo.spec_codes(db, [p.spec_id for p in pspecs] + [r.spec_id for r in rules])
    names = {sid: s.name for sid, s in repo.specs_by_ids(db, codes.keys()).items()}
    out = []
    for p in providers:
        out.append(
            AdminProviderOut(
                code=p.code,
                name=p.name,
                adapter=p.adapter,
                upstream_group=p.upstream_group,
                status=p.status,  # type: ignore[arg-type]
                updated_at=p.updated_at,
                provider_specs=[
                    AdminProviderSpecOut(
                        spec_code=codes[ps.spec_id],
                        spec_name=names[ps.spec_id],
                        provider_item_id=ps.provider_item_id,
                        cost_fen=ps.cost_fen,
                        is_enabled=ps.is_enabled,
                        last_synced_at=ps.last_synced_at,
                    )
                    for ps in pspecs
                    if ps.provider_id == p.id
                ],
                route_rules=[
                    AdminRouteRuleOut(
                        spec_code=codes[r.spec_id],
                        region_code=r.region_code,
                        priority=r.priority,
                        is_enabled=r.is_enabled,
                    )
                    for r in rules
                    if r.provider_id == p.id
                ],
            )
        )
    return out


def update_provider(
    db: Session, admin: CurrentAdmin, code: str, body: AdminProviderUpdateIn
) -> AdminProviderOut:
    provider = repo.get_provider_by_code(db, code, for_update=True)
    if provider is None:
        raise AppError(ErrorCode.NOT_FOUND, "服务商不存在")
    if provider.status != body.status:
        _audit(
            db,
            admin.id,
            "provider.update",
            "provider",
            provider.id,
            {"status": provider.status},
            {"status": body.status},
        )
        provider.status = body.status
        db.commit()
        db.refresh(provider)
    return next(p for p in list_providers(db) if p.code == code)


# ---------- 审计日志 ----------


def list_audit_logs(
    db: Session, *, admin_id: int | None, action: str | None, target_type: str | None, page: PageParams
) -> AdminAuditLogPage:
    rows = repo.list_audit_logs(
        db,
        admin_id=admin_id,
        action=action,
        target_type=target_type,
        before_id=_before_id(page.cursor),
        limit=page.limit + 1,
    )
    rows, more = _slice(rows, page.limit)
    return AdminAuditLogPage(
        items=[
            AdminAuditLogOut(
                id=log.id,
                admin_id=log.admin_id,
                admin_username=username,
                action=log.action,
                target_type=log.target_type,
                target_id=log.target_id,
                before=log.before,
                after=log.after,
                created_at=log.created_at,
            )
            for log, username in rows
        ],
        next_cursor=encode_cursor({"i": rows[-1][0].id}) if more and rows else None,
    )
