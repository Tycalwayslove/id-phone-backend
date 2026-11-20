# T017 小程序跟进（续费、退款中、照片检测提示）

- 状态：进行中（Codex，Wave 4）
- 依赖：T012、T014 已合入（PR #7）

## 目标
让小程序跟上 Wave 3 的后端变化。

## 只允许改的文件
`miniapp/src/`（含重新生成的接口类型，如有）。

## 要求
1. 续费入口：权益详情/列表根据 `can_renew` 显示“续费”；下单带 `renew_entitlement_id`（续费时不传 `photo_id`、`parent_entitlement_id`）。`can_renew=false` 不显示。
2. 订单 `refund_pending=true` 时显示“退款中”，不显示已退款完成。
3. 照片导出/下载/回执提交遇 `PHOTO_NOT_READY` 提示“照片检测中，请稍后再试”；遇 `PHOTO_REJECTED` 提示“照片未通过内容检测，请更换照片”。
4. 提示文案对用户友好，不暴露内部错误码。

## 验收
- 小程序 typecheck、build 通过，CI 全绿。
