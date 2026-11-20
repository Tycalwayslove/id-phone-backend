# T011 小程序合规与私域引导

- 状态：进行中（Codex）
- 依赖：无（Wave 1）

## 目标
补齐小程序审核必需的隐私与协议，并加私域引导和订阅授权入口。

## 只允许改的文件
`miniapp/src/app.config.ts`、`miniapp/src/pages/legal/`（新）、`miniapp/src/components/PrivacyPopup/`（新）、`miniapp/src/components/PrivateDomainCard/`（新）、`miniapp/src/pages/me/`、`miniapp/src/pages/index/`。

## 要求
1. 隐私授权弹窗：配置 `__usePrivacyCheck__`，用 `wx.onNeedPrivacyAuthorization` 等接口，拒绝后不能调用隐私接口。
2. 用户协议、隐私政策页：正文先放占位文本，真实正文由用户提供（法务确认）。
3. 企业微信 / 公众号引导卡片：二维码与链接从 `TARO_APP_*` 环境变量读，不写死；未配置时不显示。
4. 回执结果与到期提醒的订阅消息授权入口（模板 ID 从环境变量读）。
5. 不改接口层 `src/api/`。

## 验收
- `pnpm run gen:api && pnpm run typecheck && pnpm run build` 通过，CI 全绿。
- 新增环境变量写进报告，由主会话更新 `.env.example`。
