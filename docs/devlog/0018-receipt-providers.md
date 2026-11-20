# 0018 回执服务商适配器（T004）

- 日期：2026-11-19
- 状态：已完成适配器，接入见 T016
- 相关提交：0603627；PR #5（CI 中）

## 需求
任务单 T004：实现鹧应、黔微云两个真实适配器，`RECEIPT_MODE=real` 时 `get_provider` 按 adapter 返回。对接说明见 `docs/integrations/zheying.md`。

## 拆解
1. 两家共用实现 `_zjz_common`，`zheying.py`、`clipimg.py` 只做薄封装。
2. `submit` / `parse_callback` / `query`，状态映射。
3. 回调一次性 nonce 的生成函数。
4. `httpx.MockTransport` 单测。
5. receipts 模块侧接入拆成 T016。

## 方案与决定
- `submit` 串行调 `/receipt/make` 与 `/receipt/submit`；超时或结果不确定抛 `TimeoutError`（服务商无幂等，不重试），`code!=0` 抛 `PROVIDER_UNAVAILABLE`。
- `parse_callback` 常量时间校验 sign；状态映射 2 为 processing，3/4 为 completed，-1 为 rejected，-2 为 failed。
- 服务商无查询接口，`query()` 返回 processing。
- 回调验签弱（sign 是 key 的固定 MD5），故回调 URL 带每次提交随机生成的一次性 nonce（`build_callback_url()`），绑定 attempt；nonce 的持久化与校验、归属与状态迁移校验、可选 IP 白名单、超时人工核对都在 receipts 模块，由 T016 做。

## 改动
- `backend/app/integrations/receipt_providers/`：`__init__.py`、新增 `_zjz_common.py`，`zheying.py`、`clipimg.py` 补实现。
- 测试 `backend/tests/integrations/test_receipt_zheying.py`；`docs/integrations/zheying.md` 补充。

## 验证
- 单测由 Codex 编写；ruff 与 CI 由 Claude 执行，PR #5 的 CI 全绿（test、admin-web、miniapp）后合入。
- 未接真实服务商（无账号）。

## 遗留与下一步
- T016：receipts 模块接入。
- 需要用户提供鹧应 / 黔微云账号与密钥（见 `docs/progress.md`）。
