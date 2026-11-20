# T004 回执服务商正式对接

- 状态：待开始（对接说明已完成，见 `docs/integrations/zheying.md`；编码需要用户提供鹧应、黔微云账号与密钥）
- 对接说明已完成（`docs/integrations/zheying.md`）。

## 目标
实现 `backend/app/integrations/receipt_providers/` 下的 `zheying.py`、`clipimg.py` 两个真实适配器，实现 `base.py` 的 `ReceiptProvider` 接口（submit / query / parse_callback），`__init__.py` 的 `get_provider` 在 `RECEIPT_MODE=real` 时按 adapter 返回它们。

## 要求
- 接口文档：鹧应 https://zjzapi.com/doc/quick-start.html ，黔微云 https://www.qwyun.top/doc/quick-start.html （两家同一上游，接口形态相近，先做鹧应）。
- 对接说明已写好（见上）：先写一份对接说明 `docs/integrations/zheying.md`：鉴权方式、提交接口、查询接口、回调格式与签名、状态码映射到 processing/completed/rejected/failed、费用、限流、测试环境。写完交给 Claude 评审后再编码。
- 网络超时抛 `TimeoutError`（业务层会当“结果未知”处理并轮询），不要当失败。
- 用 `httpx.MockTransport` 写适配器单测：正常提交、驳回、成功出回执、签名错误、超时。
- 密钥只从配置读（`ZHEYING_APP_KEY` 等），不进日志。

## 只允许改的文件
`backend/app/integrations/receipt_providers/`、`backend/tests/integrations/`、`docs/integrations/`。

## T004 补充决定（Claude，基于对接说明）
- **回调验签弱**（sign 是 key 的固定 MD5）：回调 URL 带每次提交随机生成的一次性 nonce（绑定 attempt，不是登录令牌，不违反“令牌不进 URL”）；校验 sign + nonce + order_no 归属 + 状态迁移合法；可选来源 IP 白名单（配置项）；nonce 与 sign 不进日志。
- **无查询接口**：`query()` 返回 processing；poller 对超过阈值（如 2 小时）仍 processing 的 attempt 标记“需人工核对”，后台可见。
- **提交流程**：`submit` 内部串行调 `/receipt/make` 再 `/receipt/submit`；超时不自动重试（无幂等），抛 `TimeoutError`，业务层按“结果未知”处理；提交成功立即保存 order_no 与 attempt 的映射。
- **配置项**：`ZHEYING_BASE_URL`、`ZHEYING_APP_KEY`、`ZHEYING_CALLBACK_IP_ALLOWLIST`；黔微云同形 `QWYUN_*`。
