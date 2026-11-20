# 0023 receipts 接入真实服务商（T016）

- 日期：2026-11-19
- 状态：已完成（真实服务商联调待账号）
- 相关提交：9a3723d；PR #6

## 需求
任务单 T016：让 receipts 模块安全使用 T004 的真实适配器，`RECEIPT_MODE=fake` 行为不变。

## 拆解
1. nonce 生成、存储、校验。
2. 回调归属与状态迁移校验、可选 IP 白名单。
3. 回执图片转存。
4. 超时人工核对。

## 方案与决定
- 提交前生成一次性回调 nonce，只存 SHA-256 摘要，绑定 attempt，不进日志。
- 回调校验：签名、nonce、服务商与单号归属、来源 IP 白名单（`RECEIPT_CALLBACK_IP_ALLOWLIST`，逗号分隔，留空不限）、状态迁移合法，已终态不再变化并去重。
- 回执图片由 worker 下载转存到 storage（`receipt_image.py`）；状态 4 补存物流。
- 服务商无查询接口：真实通道 2 小时无结果标记 `manual_review_required`，交人工核对。
- 无需迁移。

## 改动
- `backend/app/modules/receipts/{poller,receipt_image,repo,router,schemas,service}.py`。
- 配置 `RECEIPT_CALLBACK_IP_ALLOWLIST` 及 `.env.example`。
- 测试：`backend/tests/receipts/test_real_receipts.py`、`test_receipt_callback_units.py`。

## 验证
- CI 全绿（273 个测试），fake 模式原有测试不变。

## 遗留与下一步
- 需要鹧应 / 黔微云账号与密钥，以及公网回调地址，做真实联调。
- 后台对“需人工核对”的处理界面可在 T010 后续补。
