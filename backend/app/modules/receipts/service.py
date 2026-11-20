"""回执业务：创建申请、驳回重提、取消、应用服务商结果、回调与联调。

事务：对外入口（create/resubmit/cancel/handle_callback/simulate）在这里 commit；
apply_provider_status 只 flush，由调用方（回调、轮询、联调）统一 commit。
日志和 request_payload 里不出现完整身份证号和姓名。
"""

import hashlib
import json
import logging
import re
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import settings
from app.core.deps import PageParams
from app.core.errors import AppError, ErrorCode
from app.core.idempotency import run_idempotent
from app.core.schemas import OkResponse
from app.core.utils import decode_cursor, encode_cursor, new_no, utcnow
from app.integrations.receipt_providers import get_provider
from app.integrations.receipt_providers.base import ProviderStatus, SubmitRequest
from app.integrations.receipt_providers.fake import FakeProvider
from app.integrations.storage import get_storage
from app.models import (
    Entitlement,
    File,
    Provider,
    ProviderCallback,
    ProviderSpec,
    ReceiptApplication,
    ReceiptAttempt,
    Spec,
)
from app.modules.entitlements import service as ent_service
from app.modules.photos import service as photo_service
from app.modules.receipts import repo
from app.modules.receipts.schemas import (
    ApplicationOut,
    ApplicationPage,
    AttemptOut,
    ReceiptCreate,
    ResubmitRequest,
    SimulateRequest,
)

log = logging.getLogger("app.receipts")

_IDCARD_RE = re.compile(r"^\d{17}[\dXx]$")
_TERMINAL = ("completed", "rejected", "failed", "abandoned")

SUBMITTED_POLL_DELAY = timedelta(minutes=5)
UNKNOWN_POLL_DELAY = timedelta(minutes=2)
PROCESSING_POLL_DELAY = timedelta(minutes=10)


# ---------- 脱敏与表单 ----------


def _mask_idcard(value: str) -> str:
    return value[:3] + "*" * (len(value) - 7) + value[-4:] if len(value) >= 8 else "****"


def mask_form(form: dict[str, str]) -> dict[str, str]:
    """姓名只留姓，身份证只留前 3 后 4，手机号中间打码。"""
    out: dict[str, str] = {}
    for key, value in form.items():
        if key == "name":
            out[key] = value[:1] + "*" if value else ""
        elif key == "idcard":
            out[key] = _mask_idcard(value)
        elif key in ("mobile", "phone"):
            out[key] = security.mask_phone(value)
        else:
            out[key] = value
    return out


def _clean_form(spec: Spec, raw: dict[str, str]) -> dict[str, str]:
    """按规格 form_schema 校验：必填项非空；有身份证号时检查格式。"""
    schema = spec.form_schema or []
    cleaned: dict[str, str] = {}
    for field in schema:
        key = field["key"]
        value = (raw.get(key) or "").strip()
        if field.get("required") and not value:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"缺少：{field.get('label') or key}")
        if value:
            cleaned[key] = value
    if not schema:
        cleaned = {k: v.strip() for k, v in raw.items() if v and v.strip()}
    idcard = cleaned.get("idcard")
    if idcard is not None:
        if not _IDCARD_RE.match(idcard):
            raise AppError(ErrorCode.VALIDATION_ERROR, "身份证号格式不正确")
        cleaned["idcard"] = idcard.upper()
    return cleaned


def _load_form(app: ReceiptApplication) -> dict[str, str]:
    if not app.form_data_enc:
        return {}
    return json.loads(security.decrypt(app.form_data_enc, "receipt_form"))


# ---------- 拼装返回 ----------


def _build_outs(db: Session, apps: list[ReceiptApplication]) -> list[ApplicationOut]:
    specs = repo.specs_by_ids(db, (a.spec_id for a in apps))
    ents = repo.entitlements_by_ids(db, (a.entitlement_id for a in apps))
    attempts = repo.attempts_by_app_ids(db, (a.id for a in apps))
    files = repo.files_by_ids(db, (a.receipt_file_id for a in apps if a.receipt_file_id))
    outs = []
    for a in apps:
        spec = specs[a.spec_id]
        file = files.get(a.receipt_file_id) if a.receipt_file_id else None
        receipt_url = (
            photo_service.file_url(file)
            if a.status == "completed" and file and file.status == "active"
            else None
        )
        outs.append(
            ApplicationOut(
                app_no=a.app_no,
                status=a.status,  # type: ignore[arg-type]
                spec_code=spec.code,
                spec_name=spec.name,
                photo_id=a.photo_id,
                entitlement_id=a.entitlement_id,
                reject_reason=a.reject_reason,
                rejected_at=a.rejected_at,
                resubmit_count=a.resubmit_count,
                resubmit_left=max(ent_service.resubmit_limit(ents[a.entitlement_id]) - a.resubmit_count, 0),
                image_code=a.image_code,
                receipt_url=receipt_url,
                official_expire_at=a.official_expire_at,
                completed_at=a.completed_at,
                created_at=a.created_at,
                form_masked=mask_form(_load_form(a)),
                attempts=[AttemptOut.model_validate(x) for x in attempts.get(a.id, [])],
            )
        )
    return outs


def _build_out(db: Session, app: ReceiptApplication) -> ApplicationOut:
    return _build_outs(db, [app])[0]


def _get_owned(db: Session, user_id: int, app_no: str, *, for_update: bool = False) -> ReceiptApplication:
    app = repo.get_application(db, user_id, app_no, for_update=for_update)
    if app is None:
        raise AppError(ErrorCode.APPLICATION_NOT_FOUND)
    return app


# ---------- 查询 ----------


def list_applications(db: Session, *, user_id: int, page: PageParams) -> ApplicationPage:
    cur = decode_cursor(page.cursor)
    before_id = cur.get("i") if cur and isinstance(cur.get("i"), int) else None
    rows = repo.list_applications(db, user_id, before_id=before_id, limit=page.limit + 1)
    has_more = len(rows) > page.limit
    rows = rows[: page.limit]
    next_cursor = encode_cursor({"i": rows[-1].id}) if has_more else None
    return ApplicationPage(items=_build_outs(db, rows), next_cursor=next_cursor)


def get_application_detail(db: Session, *, user_id: int, app_no: str) -> ApplicationOut:
    return _build_out(db, _get_owned(db, user_id, app_no))


# ---------- 提交 ----------


def _submit_attempt(
    db: Session,
    app: ReceiptApplication,
    spec: Spec,
    form: dict[str, str],
    route: tuple[Provider, ProviderSpec],
) -> ReceiptAttempt:
    """生成一次提交记录并发给服务商。首次提交和驳回重提共用。"""
    provider, provider_spec = route
    bg_color = spec.bg_colors[0] if spec.bg_colors else "#FFFFFF"
    render = photo_service.render(
        db,
        user_id=app.user_id,
        photo_id=app.photo_id,
        spec=spec,
        bg_color=bg_color,
        beauty_level=0,
        watermarked=False,
    )
    file = db.get(File, render.file_id)
    photo_bytes = get_storage().get(file.storage_key)

    repo.demote_current(db, app.id)  # 先把旧的当前提交置为非当前，避免部分唯一索引冲突
    attempt = ReceiptAttempt(
        application_id=app.id,
        seq=repo.last_seq(db, app.id) + 1,
        provider_id=provider.id,
        render_id=render.id,
        is_current=True,
        status="created",
        request_payload={"spec_code": spec.code, "region_code": app.region_code, "form": mask_form(form)},
    )
    db.add(attempt)
    db.flush()

    now = utcnow()
    try:
        order_no = get_provider(provider.adapter, provider.code).submit(
            SubmitRequest(
                attempt_ref=f"{app.app_no}-{attempt.seq}",
                provider_item_id=provider_spec.provider_item_id,
                photo=photo_bytes,
                photo_mime=file.mime,
                form=form,
                region_code=app.region_code,
            )
        )
    except TimeoutError:
        # 无法确认对方是否收到：不算失败，稍后轮询核对
        attempt.status = "unknown"
        attempt.next_poll_at = now + UNKNOWN_POLL_DELAY
        app.status = "processing"
    except Exception as e:
        log.warning("回执提交失败 app=%s seq=%s err=%s", app.app_no, attempt.seq, type(e).__name__)
        attempt.status = "failed"
        attempt.finished_at = now
        app.status = "failed"
        ent_service.release_quota(db, app.entitlement_id, app.id)
    else:
        attempt.status = "submitted"
        attempt.provider_order_no = order_no
        attempt.submitted_at = now
        attempt.next_poll_at = now + SUBMITTED_POLL_DELAY
        app.status = "processing"
    db.flush()
    return attempt


def _create(db: Session, user_id: int, payload: ReceiptCreate) -> ApplicationOut:
    from app.modules.specs import service as spec_service

    spec = spec_service.get_active_spec(db, payload.spec_code)
    route = repo.find_route(db, spec.id, payload.region_code)
    if route is None:
        raise AppError(ErrorCode.RECEIPT_NOT_SUPPORTED)
    photo_service.get_photo_for_user(db, user_id, payload.photo_id)
    form = _clean_form(spec, payload.form)
    ent = ent_service.pick_for_receipt(db, user_id, payload.photo_id)

    idcard_hash = security.keyed_hash(form["idcard"], "idcard") if "idcard" in form else None
    if (ent.benefits_snapshot or {}).get("one_person"):
        if idcard_hash is None:
            raise AppError(ErrorCode.VALIDATION_ERROR, "缺少：身份证号")
        ent_service.bind_or_check_person(db, ent, idcard_hash)

    app = ReceiptApplication(
        app_no=new_no("R"),
        user_id=user_id,
        photo_id=payload.photo_id,
        spec_id=spec.id,
        entitlement_id=ent.id,
        region_code=payload.region_code,
        form_data_enc=security.encrypt(json.dumps(form, ensure_ascii=False), "receipt_form"),
        idcard_hash=idcard_hash,
        status="pending",
    )
    db.add(app)
    db.flush()
    ent_service.reserve_quota(db, ent.id, app.id)
    _submit_attempt(db, app, spec, form, route)
    return _build_out(db, app)


def create_application(
    db: Session, *, user_id: int, idem_key: str | None, payload: ReceiptCreate
) -> ApplicationOut:
    return run_idempotent(
        db,
        user_id=user_id,
        scope="receipts.create",
        key=idem_key,
        request=payload.model_dump(mode="json"),
        produce=lambda: _create(db, user_id, payload),
        out_model=ApplicationOut,
    )


def _resubmit(db: Session, user_id: int, app_no: str, payload: ResubmitRequest) -> ApplicationOut:
    app = _get_owned(db, user_id, app_no, for_update=True)
    if app.status != "rejected":
        raise AppError(ErrorCode.APPLICATION_NOT_RESUBMITTABLE)
    ent = db.get(Entitlement, app.entitlement_id)
    if app.resubmit_count >= ent_service.resubmit_limit(ent):
        raise AppError(ErrorCode.RESUBMIT_LIMIT_REACHED)
    if ent.status != "active" or ent.ends_at <= utcnow():
        raise AppError(ErrorCode.ENTITLEMENT_EXPIRED)
    if payload.photo_id is not None:
        photo_service.get_photo_for_user(db, user_id, payload.photo_id)
    spec = db.get(Spec, app.spec_id)
    route = repo.find_route(db, spec.id, app.region_code)
    if route is None:
        raise AppError(ErrorCode.RECEIPT_NOT_SUPPORTED)

    # 额度在创建申请时已预占、驳回时没有释放，这里不再预占
    app.resubmit_count += 1
    if payload.photo_id is not None:
        app.photo_id = payload.photo_id
    app.reject_reason = None
    app.rejected_at = None
    _submit_attempt(db, app, spec, _load_form(app), route)
    return _build_out(db, app)


def resubmit_application(
    db: Session, *, user_id: int, idem_key: str | None, app_no: str, payload: ResubmitRequest
) -> ApplicationOut:
    return run_idempotent(
        db,
        user_id=user_id,
        scope="receipts.resubmit",
        key=idem_key,
        request={"app_no": app_no, **payload.model_dump(mode="json")},
        produce=lambda: _resubmit(db, user_id, app_no, payload),
        out_model=ApplicationOut,
    )


def cancel_application(
    db: Session, *, user_id: int, app_no: str, for_refund: bool = False
) -> ReceiptApplication:
    """取消申请并释放额度。全额退款还可取消 processing 的申请。不 commit。"""
    app = _get_owned(db, user_id, app_no, for_update=True)
    allowed = repo.REFUND_CANCELLABLE_STATUSES if for_refund else ("pending", "rejected")
    if app.status not in allowed:
        raise AppError(ErrorCode.APPLICATION_NOT_RESUBMITTABLE)
    ent_service.release_quota(db, app.entitlement_id, app.id)  # 已释放过的重复调用无副作用
    app.status = "cancelled"
    db.flush()
    return app


def cancel_for_refund(db: Session, entitlement_ids: set[int]) -> None:
    """取消撤销权益下尚未办结的申请。不 commit。"""
    for app in repo.lock_refundable_applications(db, entitlement_ids):
        cancel_application(db, user_id=app.user_id, app_no=app.app_no, for_refund=True)


def cancel_application_out(db: Session, *, user_id: int, app_no: str) -> ApplicationOut:
    out = _build_out(db, cancel_application(db, user_id=user_id, app_no=app_no))
    db.commit()
    return out


# ---------- 应用服务商结果 ----------


def apply_provider_status(db: Session, attempt: ReceiptAttempt, status: ProviderStatus) -> str:
    """把服务商结果应用到尝试和申请上，返回 applied / stale / duplicate。只 flush，不 commit。"""
    from app.modules.notify import service as notify_service

    if not attempt.is_current:
        return "stale"
    if attempt.status in _TERMINAL:
        return "duplicate" if attempt.status == status.result else "stale"
    app = repo.get_application_by_id(db, attempt.application_id, for_update=True)
    if app is None or app.status not in ("pending", "processing"):
        return "stale"

    now = utcnow()
    if status.result == "processing":
        attempt.status = "processing"
        attempt.next_poll_at = now + PROCESSING_POLL_DELAY
        app.status = "processing"
    elif status.result == "completed":
        spec = db.get(Spec, app.spec_id)
        if status.receipt_image:
            mime = status.receipt_mime or "image/png"
            file = photo_service.save_file(
                db,
                user_id=app.user_id,
                kind="receipt",
                data=status.receipt_image,
                mime=mime,
                ext="png" if mime == "image/png" else "jpg",
                owner=f"a{app.id}",
            )
            app.receipt_file_id = file.id
        else:
            log.warning("回执完成但没有回执图片 app=%s", app.app_no)
        expire_at = status.official_expire_at
        if expire_at is None and spec.official_valid_days:
            expire_at = now + timedelta(days=spec.official_valid_days)
        attempt.status = "completed"
        attempt.finished_at = now
        attempt.next_poll_at = None
        app.status = "completed"
        app.image_code = status.image_code
        app.completed_at = now
        app.official_expire_at = expire_at
        ent_service.confirm_quota(db, app.entitlement_id, app.id)
        notify_service.create_task(db, user_id=app.user_id, event="receipt_completed", application_id=app.id)
    elif status.result == "rejected":
        attempt.status = "rejected"
        attempt.reject_reason = status.reject_reason
        attempt.finished_at = now
        attempt.next_poll_at = None
        app.status = "rejected"
        app.reject_reason = status.reject_reason
        app.rejected_at = now
        notify_service.create_task(db, user_id=app.user_id, event="receipt_rejected", application_id=app.id)
        ent = db.get(Entitlement, app.entitlement_id)
        if app.resubmit_count >= ent_service.resubmit_limit(ent):
            # 没有重提机会了：最终放弃，释放预占的额度（状态仍保持 rejected）
            ent_service.release_quota(db, app.entitlement_id, app.id)
    else:  # failed
        attempt.status = "failed"
        attempt.reject_reason = status.reject_reason
        attempt.finished_at = now
        attempt.next_poll_at = None
        app.status = "failed"
        ent_service.release_quota(db, app.entitlement_id, app.id)
    db.flush()
    return "applied"


# ---------- 服务商回调 ----------


def handle_callback(db: Session, *, provider_code: str, headers: dict[str, str], body: bytes) -> OkResponse:
    provider = repo.get_provider_by_code(db, provider_code)
    if provider is None:
        raise AppError(ErrorCode.NOT_FOUND)
    adapter = get_provider(provider.adapter, provider.code)
    try:
        status, dedupe_key = adapter.parse_callback(headers, body)
    except AppError as e:
        if e.code == ErrorCode.CALLBACK_SIGNATURE_INVALID:
            # 抛错会回滚，所以先把这次无效回调记下来并提交，再抛错
            db.add(
                ProviderCallback(
                    provider_id=provider.id,
                    event_status="unknown",
                    payload={"body_sha256": hashlib.sha256(body).hexdigest(), "size": len(body)},
                    signature_ok=False,
                    dedupe_key=f"invalid:{provider.code}:{secrets.token_hex(8)}",
                    process_result="error",
                    processed_at=utcnow(),
                )
            )
            db.commit()
        raise
    except (ValueError, KeyError, TypeError) as e:
        raise AppError(ErrorCode.VALIDATION_ERROR, "回调内容格式不正确") from e

    if repo.get_callback_by_dedupe(db, dedupe_key) is not None:
        return OkResponse()  # 重复回调：已处理过，直接返回成功

    attempt = repo.get_attempt_by_order(db, provider.id, status.provider_order_no)
    callback = ProviderCallback(
        provider_id=provider.id,
        attempt_id=attempt.id if attempt else None,
        provider_order_no=status.provider_order_no,
        event_status=status.result,
        payload=_callback_payload(status),
        signature_ok=True,
        dedupe_key=dedupe_key,
        process_result="pending",
    )
    try:
        with db.begin_nested():
            db.add(callback)
            db.flush()
    except IntegrityError:
        return OkResponse()  # 并发的同一回调已被另一个请求占住

    if attempt is None:
        callback.process_result = "unmatched"
    else:
        callback.process_result = apply_provider_status(db, attempt, status)
    callback.processed_at = utcnow()
    db.commit()
    return OkResponse()


def _callback_payload(status: ProviderStatus) -> dict[str, Any]:
    """回调落库的内容：不存回执图片本身，只存元信息。"""
    return {
        "provider_order_no": status.provider_order_no,
        "result": status.result,
        "reject_reason": status.reject_reason,
        "image_code": status.image_code,
        "has_receipt_image": status.receipt_image is not None,
    }


# ---------- 联调 ----------


def simulate_result(db: Session, *, user_id: int, app_no: str, payload: SimulateRequest) -> ApplicationOut:
    """联调：用假通道给本人申请的当前提交模拟一个结果。非 fake 模式不可用。"""
    app = _get_owned(db, user_id, app_no)
    if settings.receipt_mode != "fake":
        raise AppError(ErrorCode.NOT_FOUND)
    attempt = repo.get_current_attempt(db, app.id)
    if attempt is None or not attempt.provider_order_no:
        raise AppError(ErrorCode.NOT_FOUND, "没有可以模拟结果的提交记录")
    provider = db.get(Provider, attempt.provider_id)
    adapter = get_provider(provider.adapter, provider.code)
    if not isinstance(adapter, FakeProvider):
        raise AppError(ErrorCode.NOT_FOUND)
    status = adapter.simulate(attempt.provider_order_no, payload.result, payload.reject_reason)
    apply_provider_status(db, attempt, status)
    db.commit()
    return _build_out(db, app)
