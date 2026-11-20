# 0017 小程序合规与私域引导（T011）

- 日期：2026-11-19
- 状态：已完成
- 相关提交：dbaf2fb、f96e26a、cab81e6；PR #4

## 需求
任务单 T011：补齐小程序审核必需的隐私授权与协议页，并加私域引导和订阅授权入口。

## 拆解
1. 隐私授权弹窗与 `__usePrivacyCheck__`。
2. 用户协议、隐私政策页。
3. 企业微信 / 公众号引导卡片。
4. 回执结果与到期提醒的订阅消息授权入口。
5. 补环境变量占位。

## 方案与决定
- 开启 `__usePrivacyCheck__`，首页挂载隐私授权弹窗（同意 / 拒绝 / 查看隐私政策）；微信审核要求隐私授权与协议页，这是上架前置条件。
- 协议页正文为占位，待法务确认。“我的”页加入口。
- 引导卡片的链接与文案来自 `TARO_APP_WECOM_*`、`TARO_APP_MP_*`，未配置不显示。
- “我的”页消息提醒设置：模板 ID 来自 `TARO_APP_TPL_*`，只上报用户允许的模板。
- 不改接口层 `src/api/`。
- Claude 评审补充：`openPrivacyContract` 的类型定义不返回 Promise，改用 `fail` 回调（cab81e6）。

## 改动
- `miniapp/src/app.config.ts`；新增 `components/PrivacyPopup/`、`components/PrivateDomainCard/`、`pages/legal/`（agreement、privacy）；改 `pages/index/`、`pages/me/`（含 `ReminderSettings.tsx`）。
- `miniapp/.env.development`、`.env.production` 补变量占位。

## 验证
- `pnpm run gen:api && pnpm run typecheck && pnpm run build`；PR #4 合入 main，CI 全绿。
- 未做真机验证。

## 遗留与下一步
- 需要用户提供：隐私政策与用户协议正文、企业微信 / 公众号信息、订阅消息模板 ID（见 `docs/progress.md`）。
- 小程序后台需配置隐私保护指引，真机验证弹窗行为。
