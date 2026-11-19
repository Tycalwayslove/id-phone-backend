# T004 回执服务商正式对接

- 状态：待开始（需要用户提供鹧应、黔微云账号与密钥）

## 目标
实现 `backend/app/integrations/receipt_providers/` 下的 `zheying.py`、`clipimg.py` 两个真实适配器，实现 `base.py` 的 `ReceiptProvider` 接口（submit / query / parse_callback），`__init__.py` 的 `get_provider` 在 `RECEIPT_MODE=real` 时按 adapter 返回它们。

## 要求
- 接口文档：鹧应 https://zjzapi.com/doc/quick-start.html ，黔微云 https://www.qwyun.top/doc/quick-start.html （两家同一上游，接口形态相近，先做鹧应）。
- 先写一份对接说明 `docs/integrations/zheying.md`：鉴权方式、提交接口、查询接口、回调格式与签名、状态码映射到 processing/completed/rejected/failed、费用、限流、测试环境。写完交给 Claude 评审后再编码。
- 网络超时抛 `TimeoutError`（业务层会当“结果未知”处理并轮询），不要当失败。
- 用 `httpx.MockTransport` 写适配器单测：正常提交、驳回、成功出回执、签名错误、超时。
- 密钥只从配置读（`ZHEYING_APP_KEY` 等），不进日志。

## 只允许改的文件
`backend/app/integrations/receipt_providers/`、`backend/tests/integrations/`、`docs/integrations/`。
