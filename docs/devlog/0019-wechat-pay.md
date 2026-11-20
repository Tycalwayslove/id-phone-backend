# 0019 微信支付 APIv3 正式接入（T005）

- 日期：2026-11-19
- 状态：已完成（真实商户号联调待账号）
- 相关提交：b6a77e8、b68bb63（runner 接线与共享文件）；PR #6

## 需求
任务单 T005：实现 `integrations/payment.py` 的 `WechatPay`，JSAPI 下单返回 wx.requestPayment 参数，支付通知验签与解密，退款，查单，关单；支付回调按微信要求应答。

## 拆解
1. 请求签名（SHA256-RSA）与响应、通知验签。
2. 通知解密（AEAD_AES_256_GCM）。
3. JSAPI 下单、查单、关单、退款。
4. orders 模块：支付与退款回调应答格式、取消订单关单、退款异步化。
5. 退款通知丢失的补偿任务接入 runner。

## 方案与决定
- 任务单允许引入 SDK，评审后不引：用 `cryptography` + `httpx` 自实现，依赖更少、可用 `MockTransport` 与自生成密钥对完整测试。
- 验签支持平台证书，也支持微信支付公钥（`WXPAY_PUBLIC_KEY_PATH`、`WXPAY_PUBLIC_KEY_ID`），可切换期同时配置。
- 回调应答：成功 204，失败 `{"code":"FAIL","message":"..."}`。
- 退款是异步的：沿用 T003 的 `request_id` 作为退款单号（幂等）；处理中占用余额，确认成功后只入账一次。
- 新增 `poll_pending_refunds`，作为退款通知丢失时的查单补偿，由主会话接入 runner（b68bb63）。
- 共享文件由主会话合并：配置分组；开启 `hide_input_in_errors`，防止配置校验报错回显密钥；后台退款接口声明 `INTERNAL_ERROR`；`CONTRACTS.md` 同步 `refund_order` 新签名。
- 无需数据库迁移。

## 改动
- `backend/app/integrations/payment.py`（约 450 行新增）。
- `backend/app/modules/orders/{router,schemas,service,repo}.py`：回调应答、退款异步、关单。
- 配置与 `.env.example`：`WXPAY_PUBLIC_KEY_PATH`、`WXPAY_PUBLIC_KEY_ID`、`WXPAY_NOTIFY_URL`、`WXPAY_REFUND_NOTIFY_URL`（留空时用 `PUBLIC_BASE_URL` 拼接，真实模式需公网 HTTPS）。
- `backend/app/workers/runner.py`：加入 `orders.poll_pending_refunds`；`docs/api/openapi.json` 更新（60 个路径）。
- 测试：`backend/tests/integrations/test_payment.py`、`backend/tests/orders/test_orders.py`。

## 验证
- PR #6 的 CI 全绿（迁移、`alembic check`、273 个测试、接口文档检查）。
- 单测用自生成密钥对，覆盖验签、解密、下单参数、退款状态流转。未接真实商户号。

## 遗留与下一步
- 需要用户提供：商户号、APIv3 密钥、证书序列号、商户私钥、平台证书或微信支付公钥、公网 HTTPS 回调地址；之后真实联调。
- T014（续费与过期加购退款）依赖本任务的异步退款设计。
