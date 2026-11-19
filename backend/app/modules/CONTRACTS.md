# 模块间约定（主会话维护）

各模块只通过下面这些 service 函数互相调用。签名改动必须先改这里。
所有函数第一个参数是 `db: Session`；不自己 commit（由调用方的 service 入口统一 commit），只 flush。

## 写法约定（每个模块都一样）

```
app/modules/<m>/
  router.py    # 只解析参数、取当前用户、调 service、返回 schemas；导出 router / admin_router / callback_router / dev_router
  schemas.py   # Pydantic 模型，继承 app.core.schemas.Schema；每个类写 docstring，每个字段写中文 description + examples
  service.py   # 业务规则、事务（入口函数里 db.commit()）；抛 AppError(ErrorCode.X)
  repo.py      # 查询；C 端查询函数第一个参数是 user_id，查不到返回 None（service 转成 404 错误码）
tests/<m>/test_*.py
```

- 路由：`operation_id` 用 `<模块>_<动作>`，如 `photos_list`；`summary` 中文短语；`description` 写用途、是否要登录、关键规则；`response_description` 必填；`responses=errors_doc(ErrorCode.A, ErrorCode.B)` 列出可能的业务错误。
- 当前用户：`me: Me`（`app.core.deps`），可选登录用 `MaybeMe`；分页用 `page: Page`，返回 `page_model(XOut, "XPage")` 生成的模型；幂等头用 `idem: IdempotencyKeyHeader` 并在 service 里用 `run_idempotent`。
- 金额字段名以 `_fen` 结尾；时间用带时区 datetime（`app.core.utils.utcnow()`）；对外编号用 `new_no("O")` 这类单号。
- 不打印手机号、身份证号、令牌。敏感字段用 `app.core.security.encrypt/keyed_hash`。

## auth（登录）

- `revoke_all_for_user(db, user_id) -> int`：吊销该用户全部会话，返回数量。

## photos（照片与文件）

- `save_file(db, *, user_id, kind, data, mime, ext, owner, spec_code=None, bg=None, beauty=None) -> File`
  存到 `get_storage()`，按命名规则生成 key，写 files 表。kind ∈ original/matting/preview/render/receipt；owner 形如 `p12` 或 `a34`。
- `file_url(file: File, expires_in: int = 600) -> str`：签名下载链接。
- `get_photo_for_user(db, user_id, photo_id) -> Photo`：不是本人的或不存在 → `AppError(PHOTO_NOT_FOUND)`。
- `render(db, *, user_id, photo_id, spec: Spec, bg_color, beauty_level, watermarked) -> PhotoRender`：同参数已有就复用；没有就用 Pillow 生成并保存。
- `purge_all_for_user(db, user_id) -> int`：删除该用户全部存储文件，files 标记 purged，photos 标记 purged。

## entitlements（权益）

- `grant_for_order_item(db, *, user_id, item: OrderItem, plan: Plan, paid_at) -> Entitlement`
  按套餐权益生成 entitlement 和 entitlement_quotas。`attach_to_parent=1` 的加购项：`item.snapshot["parent_entitlement_id"]` 指向主权益，到期时间、photo_id 跟主权益一致。照片范围 `photo_scope=1` 时 photo_id 取 `item.photo_id`。
- `photo_access(db, user_id, photo_id) -> PhotoAccess`：`PhotoAccess(active: bool, access_until: datetime | None, spec_change: bool)`。有效权益 = status active、未过期、且（photo_id 等于这张照片，或 photo_scope=0 覆盖全部照片）。
- `pick_for_receipt(db, user_id, photo_id) -> Entitlement`：选一个覆盖该照片、未过期、回执额度还有剩余的权益（到期早的优先）。没有有效权益 → `ENTITLEMENT_EXPIRED`；有但额度用完 → `QUOTA_EXHAUSTED`。
- `resubmit_limit(ent) -> int`：从 benefits_snapshot 读重提次数，默认 0。
- `bind_or_check_person(db, ent, idcard_hash) -> None`：一卡一人的权益，第一次绑定身份证哈希，之后不一致 → `ONE_PERSON_MISMATCH`。
- `reserve_quota(db, ent_id, application_id)` / `confirm_quota(...)` / `release_quota(...)`：回执额度预占、确认、释放。用 entitlement_ledger 保证同一申请同一动作只执行一次（重复调用无副作用）。reserve 使 used+1（超额 → QUOTA_EXHAUSTED），release 使 used-1，confirm 不改 used。

## orders（套餐与订单）

- `get_plan_by_code(db, code) -> Plan`：不在售 → `PLAN_NOT_AVAILABLE`。
- `mark_paid(db, *, out_trade_no, transaction_id, amount_fen, raw) -> Order`：幂等；订单变 paid，为每个订单项调用 entitlements.grant_for_order_item。

## specs（规格）

- `get_active_spec(db, code) -> Spec`：不存在或已下架 → `SPEC_NOT_FOUND`。

## notify（通知）

- `create_task(db, *, user_id, event, application_id=None, entitlement_id=None) -> NotifyTask`
  event ∈ receipt_rejected / receipt_completed / entitlement_expiring / receipt_expiring。
  同一目标同一事件已有 step=1 的任务时：若已发送过，重置为 pending 并更新 scheduled_at（再次驳回需要再通知）；否则直接返回已有任务。

## receipts（回执）

- `cancel_application(db, *, user_id, app_no) -> ReceiptApplication`：pending/rejected 的申请可取消，释放额度。
- `apply_provider_status(db, attempt, status: ProviderStatus) -> str`：把服务商结果应用到尝试和申请上，返回处理结果（applied/stale/duplicate）。轮询、回调、联调接口共用。
