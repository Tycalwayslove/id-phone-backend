# 0012 运营后台前端

- 日期：2026-11-19
- 状态：已完成
- 相关提交：feat(admin-web)：运营后台首版

## 需求

按 T001 实现运营后台，使用现有后台接口完成登录、用户、订单及退款、回执、套餐、规格、服务商与审计日志功能。

## 拆解

1. 建立 Vite 工程与 OpenAPI 类型生成，接入 Cookie 会话和权限路由。
2. 实现运营查询、订单退款和回执取消。
3. 实现套餐、规格、服务商和审计日志管理。
4. 依次验证依赖安装、类型生成、类型检查和生产构建。

## 方案与决定

- 沿用 CI 的 pnpm 10 和 ADR 0004 约定。使用 openapi-typescript 与 openapi-fetch，让端点、参数和响应以仓库 OpenAPI 为准。
- 登录通过 httpOnly Cookie 建立会话，CSRF 令牌保存在内存和当前标签页的 sessionStorage。权限取自 `GET /api/v1/admin/me`，用于菜单、路由和操作。
- 分页列表使用接口游标，筛选条件变化时从第一页开始。退款需二次确认，请求发出后锁定提交，并刷新订单和审计记录。套餐和规格编辑只提交改动字段。

## 改动

- `admin-web/` 新增工程配置、请求层、会话和布局、七个运营模块以及开发部署说明。
- `docs/progress.md`、任务单及开发日志目录记录实现和验收状态。

## 验证

- Codex（实现方）沙箱无法访问 npm 仓库，只做了静态核对：OpenAPI 的 20 个后台操作、12 个权限点、12 组枚举和 7 种权益；请求层 CSRF、403、会话失效用模拟响应检查过。
- Claude 评审后在用户 Mac 上执行 `pnpm install && pnpm run gen:api && pnpm run typecheck && pnpm run build`，全部通过（构建有 antd 包体 >500 kB 的提示，不影响）。
- 评审时补了 `admin-web/pnpm-workspace.yaml`：pnpm 10 起默认不执行依赖的安装脚本，esbuild 被拦下导致 `pnpm install` 失败；文件里同时写了 pnpm 10（CI）用的 `onlyBuiltDependencies` 和 pnpm 11+ 用的 `allowBuilds`，两个版本均验证可装。
- 推送后看 GitHub Actions 前端任务（admin-web）是否通过。

## 评审结论（Claude）

- 分层清楚：请求统一走 `src/api/`，类型全部来自生成的 schema；枚举用 `satisfies Record<...>` 绑定后端枚举，后端新增状态时类型检查会报错。
- 金额：输入用字符串解析成分，不经过浮点乘法；退款上限扣除了处理中的退款。
- 退款有二次确认和防重复提交；但后端退款接口没有幂等键，已在 T003 第 4 条。

## 遗留与下一步

- 浏览器与真实后端联调：用户本机 `cd backend && uv run uvicorn app.main:app` 后 `cd admin-web && pnpm dev`。
- 后端：退款幂等（T003 第 4 条）；手机号筛选在查询串里，部署时访问日志需省略查询串（或改为 POST 检索）——记入 T003 第 7 条。
- 上线：Nginx 同源代理 `/api` 并配置前端路由回退（`try_files ... /index.html`），写进 `docs/deploy.md` 时一起做。
- 包体积：antd 主包约 1 MB（gzip 约 350 kB），后台可接受，后续可按需拆包。
