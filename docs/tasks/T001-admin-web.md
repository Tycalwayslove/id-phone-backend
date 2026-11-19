# T001 运营后台前端 admin-web

- 状态：待开始
- 依赖：后端 admin 模块（已完成），接口见 `docs/api/openapi.json` 中 `/api/v1/admin/*`

## 目标
运营人员用的网页后台：登录、看用户/订单/回执、退款、管理套餐和规格、开关服务商、查审计日志。

## 只允许改的文件
新建 `admin-web/` 目录下的全部文件。不改其他目录。

## 技术栈（见 ADR 0004）
React 18 + Vite + TypeScript（strict）+ Ant Design 5 + React Router 6 + TanStack Query 5；pnpm。接口类型用 openapi-typescript 从 `../docs/api/openapi.json` 生成到 `src/api/schema.d.ts`（加入 .gitignore）。

package.json scripts（CI 依次执行 `pnpm install`、`pnpm run gen:api`、`pnpm run typecheck`、`pnpm run build`）：
- `gen:api`: `openapi-typescript ../docs/api/openapi.json -o src/api/schema.d.ts`
- `typecheck`: `tsc --noEmit`
- `build`: `vite build`
- `dev`: `vite`（vite.config.ts 里把 `/api` 代理到 `http://localhost:8000`，这样 Cookie 同源）

## 登录与请求
- `POST /api/v1/admin/auth/login` 成功后后端写入 httpOnly Cookie（path `/api/v1/admin`），返回 `csrf_token`：存内存 + sessionStorage。
- 所有请求 `credentials: "include"`；非 GET 请求带 `X-CSRF-Token`。
- 401（AUTH_REQUIRED / AUTH_INVALID）→ 跳登录页；403 PERMISSION_DENIED → 提示无权限。
- 根据 `GET /api/v1/admin/me` 的 permissions 控制菜单和按钮显示。

## 页面
布局：左侧菜单 + 顶部当前账号与退出。
1. 登录页
2. 用户：列表（按用户 ID、手机号、状态筛选，游标分页“加载更多”）、详情（订单数、实付总额、身份来源）
3. 订单：列表（状态、订单号、用户、时间范围）、详情（订单项、支付记录、退款记录）、退款弹窗（金额元↔分换算、原因必填、二次确认）
4. 回执：列表（状态、单号、用户、规格）、详情（提交记录时间线、驳回原因、脱敏表单）、取消办理
5. 套餐：列表（含草稿、下架）、新建/编辑（价格元↔分、权益类型下拉：storage_days、photo_scope、receipt_quota、resubmit_limit、spec_change、one_person、attach_to_parent，带中文说明）、上下架
6. 规格：列表、新建/编辑（尺寸、底色数组、表单字段 form_schema 的增删行编辑器）
7. 服务商：列表（含支持的规格、路由规则）、启用/停用/熔断切换
8. 审计日志：列表与筛选

## 验收
- CI 前端任务（admin-web）通过：生成类型、类型检查、构建。
- 状态、权益类型等枚举全部显示中文。
- 金额统一显示为元（两位小数），提交时转分。
- 写 `admin-web/README.md`；按 AGENTS.md 写 devlog、更新 progress。
