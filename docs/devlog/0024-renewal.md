# 0024 续费与订单边界（T014）

- 日期：2026-11-19
- 状态：已完成（续费退款是否回退到期时间待产品决定）
- 相关提交：3d4a5b8；PR #7

## 需求
任务单 T014：产生 `item_type=renew` 的订单，付款后延长保管期；加购付款时主权益已过期，自动全额退款并记审计；退款按“退款中”设计且幂等（真实微信退款异步）。

## 拆解
1. 续费下单校验与付款后延期。
2. 加购主权益失效、续费目标失效时的自动整单退款。
3. 订单、权益输出补前端需要的字段。

## 方案与决定
- 续费延长原权益，不新建权益：本人未撤销的独立权益，在到期前或到期后 30 天内可续费；付款后从 `max(原到期时间, 支付时间)` 起，按下单快照的 `storage_days` 延长；在订单项快照 `renewal_ledger` 记账，同一续费订单项只延期一次，重复回调幂等。
- 下单请求新增 `renew_entitlement_id`；续费时省略 `photo_id`、`parent_entitlement_id`。
- 加购主权益已过期/撤销，或续费目标失效：整单跳过发放，用支付单号派生固定 request_id 发起系统全额退款（`defer_submission=True`，由 worker 提交已入库的 pending 退款），并记审计；重复通知只返回订单。
- `mark_paid` 优先用微信支付成功时间。
- 无需迁移。
- 未决：续费订单被全额退款后，是否回退已延长的到期时间，待产品决定（当前不回退）。

## 改动
- `backend/app/modules/orders/{repo,router,schemas,service}.py`：续费下单、退款联动；订单输出新增 `refund_pending`。
- `backend/app/modules/entitlements/{router,schemas,service}.py`：`require_active_entitlement`、`require_renewable_entitlement`；权益输出新增 `can_renew`。
- `backend/app/modules/CONTRACTS.md` 同步契约。
- 测试：`backend/tests/entitlements/test_renewal.py`、`backend/tests/orders/test_orders.py`、`test_payment_boundaries.py`。

## 验证
- PR #7 CI 全绿；续费延期、过期加购退款、重复回调幂等均有测试。

## 遗留与下一步
- 续费退款回退规则等产品决定。
- 小程序续费入口与“退款中”显示见 T017。
