# 0010 小程序前端

- 日期：2026-11-19
- 状态：已完成（首版，未在真机验证）

## 需求
目标模式下实现前端，按主流商业公司的分层设计。

## 方案与决定
- Taro 4 + React + TypeScript（strict），NutUI 少量使用，其余 Taro 组件 + SCSS；zustand 存令牌；接口类型由 openapi-typescript 从 `docs/api/openapi.json` 生成（ADR 0004）。
- 请求封装：Bearer 令牌、401 静默 wx.login 重登并重试一次（并发只登录一次）、统一 ApiError 和错误码文案、Idempotency-Key。
- fake 联调：`TARO_APP_FAKE_PAY=1` 时下单走模拟支付，回执详情页可模拟结果。

## 改动
`miniapp/`：13 个页面（首页、规格列表、规格详情、制作、套餐、回执办理、我的回执、回执详情、证件照、照片详情、我的、订单、权益），通用组件、hooks、utils、README。

## 验证
CI：pnpm install → 生成接口类型 → tsc 类型检查 → taro build --type weapp 全部通过。

构建修复记录（Taro + pnpm 的坑，供以后参考）：
- `.npmrc` 设 `node-linker=hoisted`（Taro 构建链按扁平 node_modules 找依赖）
- 固定 `webpack@5.97.1`（新版本限制了子路径导入，Taro 深度引用 webpack 内部模块）
- 补 `@babel/core`、`@babel/preset-react` 等模板依赖
- tsconfig 用 `"types": ["node"]`，避免扁平安装后混入构建工具的类型包

## 遗留
- 需要真实小程序 AppID 才能在开发者工具/真机验证：getPhoneNumber、订阅消息、支付、相册权限。
- tabBar 图标、品牌插画、NutUI 主题变量待设计。
