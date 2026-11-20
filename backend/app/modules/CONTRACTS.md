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

## users（用户）

- `is_active_user(db, user_id) -> bool`：判断账户是否启用。
- `get_notification_phone(db, user_id) -> str | None`：返回启用账户已绑定的手机号，仅供短信通道使用。缺失或无法解密时返回空。

## photos（照片与文件）

- `save_file(db, *, user_id, kind, data, mime, ext, owner, spec_code=None, bg=None, beauty=None) -> File`
  存到 `get_storage()`，按命名规则生成 key，写 files 表。kind ∈ original/matting/preview/render/receipt；owner 形如 `p12` 或 `a34`。
- `file_url(file: File, expires_in: int = 600) -> str`：签名下载链接。
- `get_photo_for_user(db, user_id, photo_id) -> Photo`：不是本人的或不存在 → `AppError(PHOTO_NOT_FOUND)`。
- `render(db, *, user_id, photo_id, spec: Spec, bg_color, beauty_level, watermarked) -> PhotoRender`：同参数已有就复用；没有就用 Pillow 生成并保存。
- `purge_all_for_user(db, user_id) -> int`：删除该用户全部存储文件，files 标记 purged，photos 标记 purged。

## entitlements（权益）

- `grant_for_order_item(db, *, user_id, item: OrderItem, plan: Plan, paid_at) -> Entitlement`
  普通套餐生成权益和额度。加购项按 `item.snapshot["parent_entitlement_id"]` 锁主权益，付款时主权益有效才发放，加购到期时间与照片取自主权益。续费项按 `item.snapshot["renew_entitlement_id"]` 锁原权益，以原到期时间和付款时间的较晚值为起点，增加下单时快照中的 `storage_days`，并在订单项快照 `renewal_ledger` 中记账。同一续费订单项只延期一次。
- `require_active_entitlement(db, user_id, entitlement_id) -> Entitlement`：校验本人当前有效的主权益，供加购下单使用。
- `require_renewable_entitlement(db, user_id, entitlement_id, *, at) -> Entitlement`：校验本人未撤销、未超过到期后 30 天的独立权益。以上校验及发放在权益不存在或不属于本人时抛 `ENTITLEMENT_NOT_FOUND`，状态或期限不符时抛 `ENTITLEMENT_EXPIRED`。
- `photo_access(db, user_id, photo_id) -> PhotoAccess`：`PhotoAccess(active: bool, access_until: datetime | None, spec_change: bool)`。有效权益 = status active、未过期、且（photo_id 等于这张照片，或 photo_scope=0 覆盖全部照片）。
- `pick_for_receipt(db, user_id, photo_id) -> Entitlement`：选一个覆盖该照片、未过期、回执额度还有剩余的权益（到期早的优先）。没有有效权益 → `ENTITLEMENT_EXPIRED`；有但额度用完 → `QUOTA_EXHAUSTED`。
- `resubmit_limit(ent) -> int`：从 benefits_snapshot 读重提次数，默认 0。
- `bind_or_check_person(db, ent, idcard_hash) -> None`：一卡一人的权益，第一次绑定身份证哈希，之后不一致 → `ONE_PERSON_MISMATCH`。
- `reserve_quota(db, ent_id, application_id)` / `confirm_quota(...)` / `release_quota(...)`：回执额度预占、确认、释放。用 entitlement_ledger 保证同一申请同一动作只执行一次（重复调用无副作用）。reserve 使 used+1（超额 → QUOTA_EXHAUSTED），release 使 used-1，confirm 不改 used。

## orders（套餐与订单）

- `get_plan_by_code(db, code) -> Plan`：不在售 → `PLAN_NOT_AVAILABLE`。
- `get_plan_benefits(db, plan_id) -> dict[str, int]`：读取套餐当前权益配置，供没有下单快照的普通套餐和加购项发放时使用。
- `mark_paid(db, *, out_trade_no, transaction_id, amount_fen, raw, refund_closed=True, paid_at=None) -> Order`：幂等。优先使用微信支付成功时间，缺省使用入账时间。入账后为每个订单项发放权益或续费。加购主权益或续费目标不可用时，整单跳过权益发放，以从支付单号派生的固定请求 ID 发起系统全额退款。同一笔支付的重复通知只返回订单。

## specs（规格）

- `get_active_spec(db, code) -> Spec`：不存在或已下架 → `SPEC_NOT_FOUND`。

## notify（通知）

- `create_task(db, *, user_id, event, application_id=None, entitlement_id=None) -> NotifyTask`
  event ∈ receipt_rejected / receipt_completed / entitlement_expiring / receipt_expiring。
  同一目标同一事件已有 step=1 的任务时：若已发送过，重置为 pending 并更新 scheduled_at（再次驳回需要再通知）；否则直接返回已有任务。
- `create_task_once(db, *, user_id, event, step, application_id=None, entitlement_id=None) -> bool`：按目标、事件、档位和小程序渠道去重，返回是否新建；已有任务保留原状态，到期提醒用 step=7 和 step=1。

## receipts（回执）

- `cancel_application(db, *, user_id, app_no) -> ReceiptApplication`：pending/rejected 的申请可取消，释放额度。
- `apply_provider_status(db, attempt, status: ProviderStatus) -> str`：把服务商结果应用到尝试和申请上，返回处理结果（applied/stale/duplicate）。轮询、回调、联调接口共用。
- `list_admin_applications(db, *, before_id, limit, status=None, app_no=None, user_id=None, spec_code=None, manual_review=None)` / `get_admin_application_detail(db, *, app_no)` / `get_admin_application_by_no(db, *, app_no, for_update=False)`：供后台查询申请摘要、脱敏详情和按单号读取申请。人工核对标记只取待办理申请的当前提交。
- `application_counts_by_status(db)` / `count_user_applications(db, *, user_id)`：供后台看板和用户详情统计回执申请。
- `resolve_manual_review(db, *, app_no, result)`：锁定需人工核对的申请，通过现有状态机应用核对结论并清除标记，返回申请及原状态。调用方与审计记录一起提交。

## orders（补充）

- `refund_order(db, *, order_no, request_id, amount_fen, reason, operator, defer_submission=False) -> RefundSubmission`：后台和系统退款共用（refund、order、审计快照 before）。out_refund_no = "RA" + request_id.hex，相同请求重试返回原记录，订单或金额不同抛 IDEMPOTENCY_CONFLICT。可退余额 = 已付 − 已退 − 处理中退款。微信退款异步，处理中占用余额，确认成功后只入账一次。自动失效退款设置 `defer_submission=True`，由 worker 提交已入库的 pending 退款。全额退完撤销由该订单发放的权益。不 commit。
- `poll_pending_refunds(db, limit=10) -> int`：worker 调用，查单补偿丢失的退款通知（仅 PAY_MODE=wechat）。

## admin（后台）例外

- 回执申请查询与操作使用 receipts service。其他后台列表和详情可以直接只读查询业务表，写操作仍调用对应模块的 service。
