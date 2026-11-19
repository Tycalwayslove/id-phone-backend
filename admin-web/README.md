# 智拍证件照运营后台

使用 React 18、Vite、严格模式 TypeScript、Ant Design 5、React Router 6 和 TanStack Query 5。

## 本机开发

先按仓库的 [本机运行手册](../docs/getting-started.md) 启动后端，监听 `http://localhost:8000`。首次联调可在 `backend/` 内运行 `uv run python -m scripts.create_admin ops_dev owner`，交互设置测试账号密码。另可创建 `operator`、`finance` 账号覆盖权限场景。

使用 Node.js 22 和 pnpm 10。在 `admin-web/` 执行以下命令。

```bash
pnpm install
pnpm run gen:api
pnpm run typecheck
pnpm run build
pnpm run dev
```

打开 Vite 终端显示的地址。Vite 将同源 `/api` 请求代理到后端。接口路径、查询参数、请求体和返回类型以 `../docs/api/openapi.json` 为准。修改契约后重新运行 `pnpm run gen:api`，生成文件 `src/api/schema.d.ts` 已加入忽略规则。

## 登录与运营操作

- 后端以 httpOnly Cookie 保存会话。前端在内存和当前标签页的 `sessionStorage` 保存 CSRF 令牌，按 `/api/v1/admin/me` 返回的权限点显示页面和操作。
- 新开的独立标签页可能继承 Cookie，但缺少当前页的 CSRF 令牌。页面会提示退出后重新登录以恢复写操作。
- 金额以元显示，保存时转为整数分。退款需要二次确认，发送后同步更新订单和审计日志。请求失败时先核对退款记录，再决定是否重新操作。
- 时间按浏览器本地时区显示，时间筛选和套餐销售时间以带时区的 ISO 8601 提交。
- 手机号检索按接口要求发送完整手机号作为查询参数。列表和详情展示服务端返回的打码或脱敏数据。

## 部署

构建产物位于 `dist/`。使用 HTTPS 托管静态文件，保留同源 `/api` 代理和后端 Cookie 路径。对前端路由配置 `index.html` 回退，并让 API 路径优先走后端。代理和后端访问日志需省略查询串，防止手机号检索参数进入日志。
