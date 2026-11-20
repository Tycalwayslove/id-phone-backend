# T016 receipts 模块接入真实服务商

- 状态：已完成（PR #6，提交 9a3723d；真实服务商联调待账号；记录见 devlog 0023）
- 依赖：T004（适配器已完成）

## 目标
让 receipts 模块能安全使用 T004 的真实适配器：回调防伪、状态迁移校验、回执图转存、超时人工核对。`RECEIPT_MODE=fake` 的行为不变。

## 要做
1. nonce：提交时生成一次性 nonce（用 `build_callback_url()`），只存哈希，绑定 attempt；回调时校验 nonce，不进日志。
2. 回调归属：order_no 必须属于该 attempt；校验状态迁移合法（已终态的不再变化）。
3. 可选来源 IP 白名单：配置项 `RECEIPT_CALLBACK_IP_ALLOWLIST`（逗号分隔，留空不限制）。
4. 回执图片转存：完成时把服务商图片下载并存入 storage，不长期依赖外部链接。
5. poller：服务商无查询接口，超过 2 小时仍 processing 的 attempt 标记“需人工核对”，后台可见。
6. fake 模式行为和现有测试保持不变。

## 只允许改的文件
`backend/app/modules/receipts/`、`backend/tests/receipts/`；`backend/app/core/config.py` 与 `backend/.env.example` 只允许追加配置项；迁移如需新增，先在报告里提出，由主会话合入。

## 验收
- nonce 错误、归属不符、非法状态迁移、IP 不在白名单均被拒绝（有测试）。
- 转存、超时标记有测试。
- fake 模式原有测试全部通过；ruff、pytest 通过，CI 全绿。
