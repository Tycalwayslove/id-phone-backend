# ADR 0004 前端技术栈

- 状态：已采纳（2026-11-19）

## 决定
- **小程序**：Taro 4 + React + TypeScript，UI 用 NutUI React（Taro 版）。一套代码可编译到微信、支付宝、抖音小程序和 H5，对应“以后要做多端”的需求。
- **运营后台**：React + Vite + TypeScript + Ant Design + React Router + TanStack Query。中后台最常见的组合，组件齐全。
- **接口类型**：从后端 OpenAPI 自动生成 TypeScript 类型（openapi-typescript），前端不手写接口类型；后端改了字段，前端编译直接报错。
- **目录**：仓库根目录下 `miniapp/`、`admin-web/`，各自独立的 package.json，用 pnpm。
- **CI**：前端也在 GitHub Actions 里类型检查和构建。

## 理由
用户前端熟练（React 系），多端需求明确；类型从 OpenAPI 生成保证前后端一致。

## 代价
Taro 编译链较重，升级要谨慎；NutUI 的组件风格需要按品牌调整。
