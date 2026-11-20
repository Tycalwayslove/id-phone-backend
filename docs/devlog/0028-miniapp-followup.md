# 0028 小程序跟进：续费入口、退款中、照片检测提示（T017）

- 日期：2026-11-19
- 状态：已完成
- 相关提交：3290270；PR #8

## 需求
任务单 T017：让小程序跟上 Wave 3 的后端变化（续费 T014、照片链路 T012）。

## 拆解
1. 续费入口：按 `can_renew` 显示；下单只带 `plan_code` 与 `renew_entitlement_id`。
2. 订单 `refund_pending` 显示“退款中”。
3. `PHOTO_NOT_READY`、`PHOTO_REJECTED` 给中文提示并引导重新拍摄。

## 方案与决定
- 抽出 `EntitlementCard` 组件，权益列表与详情复用；新增权益详情页、订单详情页。
- 错误提示集中在 `utils/errors.ts`，不向用户暴露内部错误码。
- 状态文案集中在 `utils/status.ts`。

## 改动
- `miniapp/src/`：新增 `components/EntitlementCard`、`pages/entitlement-detail`、`pages/order-detail`；修改 `plans`（续费）、`entitlements`、`orders`、`editor`、`photo-detail`、`photos`、`receipt-apply`、`receipt-detail`、`PlanCard`、`StatusTag`、`app.config.ts`、`utils/{errors,nav,status}.ts`。共 23 个文件。

## 验证
- PR #8 CI 全绿：小程序 typecheck 与 build 通过。
- 未在微信开发者工具真机验证。

## 遗留与下一步
- 用户本机用微信开发者工具联调；续费退款是否回退到期时间仍待产品决定（见 0024）。
