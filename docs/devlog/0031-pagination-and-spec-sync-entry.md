# 0031 分页统一复用、规格页同步入口

- 日期：2026-11-19
- 状态：已完成
- 相关提交：7e8f1f8、834183d、401bc88、50cf6de（PR #11，CI 全绿）

## 需求
用户原话：“我在运营后台规格页面并没有发现同步规格按钮，并且现在的接口是没有分页的，这有问题，把相应的分页参数和返回值都处理好，最好能复用，然后确认其他接口的分页有没有处理好。”

## 拆解
1. 规格页加“同步规格”入口（T019 只放在服务商页的操作列里）。
2. 盘点所有列表接口的分页情况，找出没分页或分页写法不统一的。
3. 分页参数、游标解析、“多取一条判断是否还有下一页”、返回结构抽成 core 里的公共工具，各模块复用。
4. 修掉不分页的增长型列表；前端（admin-web、小程序）跟着改。

## 方案与决定
**原因**
- 同步按钮（T019）只放在服务商页操作列，且需要 `provider:write`（仅 owner 有）。现在规格页顶部也有“同步规格”下拉（选服务商），入口多了一处；非 owner 依然看不到，权限规则不变。
- 盘点结果：`/admin/specs` 本来就有游标分页；真正不分页的是 `/admin/providers`（内嵌全部规格映射和路由规则，同步全量目录后会无限增长）和 C 端 `/entitlements`（最多 100 条后截断）。

**公共分页工具（`backend/app/core/pagination.py`）**
- `PageParams`：路由参数 `page: Page`（`deps.Page`）得到统一的 cursor / limit 说明和上限（默认 20，最大 100）；提供 `fetch_limit`（多取一条）、`before_id()`、`cursor_values()`、`slice(rows)`（切出本页并生成 `next_cursor`）。
- `PageIn`：POST 请求体里带分页时继承它（如后台用户搜索），再用 `PageParams.of(body)`。
- 返回统一用 `page_model(XxxOut, "XxxPage")`，结构为 `{items, next_cursor}`；`page_model` 增加 `order` 参数，规格、权益列表的排序说明不再错写成“按创建时间”。
- 游标统一为 `{"i": id}`（排序不是 id 倒序的自己加字段，如权益用 `(到期时间, id)`）。旧游标（photos、orders 以前用 `"id"`）只会回到第一页，不报错。
- photos、orders、receipts、specs 手写的分页逻辑已改为调用公共工具；LIKE 转义挪到 `core/utils.contains_pattern`。

**有意不分页**：`/plans`、`/admin/plans`、`/notify/templates`、`/admin/providers`（固定几条配置，已在接口说明里写明）。

**接口变化（破坏性，admin-web 和小程序已同步修改）**
- `AdminProviderOut` 去掉 `provider_specs`、`route_rules`，改为 `provider_spec_count`、`enabled_provider_spec_count`、`route_rule_count`。
- 新增 `GET /admin/provider-specs`（按服务商、关键词、是否启用筛选）和 `GET /admin/route-rules`（按服务商、规格编码筛选），均为游标分页。
- `GET /admin/specs` 增加 `keyword`（名称/编码模糊）、`status`、`category` 筛选。
- `GET /entitlements` 返回 `{items, next_cursor}`（`EntitlementPage`）。

## 改动
- 后端：`core/pagination.py`（新）、`core/deps.py`、`core/schemas.py`、`core/utils.py`；photos、orders、receipts、specs、entitlements、notify、admin 各模块；`docs/api/openapi.json`；测试 `tests/system/test_pagination.py`（新）及 admin、entitlements、orders、e2e 相关测试。
- admin-web：同步逻辑抽成 `components/spec-sync.tsx`（`useSpecSync`），服务商页和规格页共用；规格页顶部加“同步规格”下拉和筛选栏；服务商详情里的规格映射、路由规则改为“加载更多”分页表格。
- 小程序：`api/entitlements.ts`、权益页改用 `usePagedList`，支持触底加载。
- 规则文档：`CLAUDE.md`、`AGENTS.md`、ADR 0005 写明模型分工只在 Claude Code 命令行生效。本需求代码由 Opus 自己写，没有按分工派 Codex，已记录并修正规则。

## 验证
- `ruff check` / `ruff format` 通过；新增 `tests/system/test_pagination.py` 本地通过。
- admin-web `typecheck` + `build` 通过。
- 数据库相关测试：本机没有 `idphone_test` 库，靠 CI 验证。
- 小程序：本机依赖装不上（pnpm 最小发布时长策略拦截了 solid-js 2.0.2），无法本地 typecheck，靠 CI 或用户本机。

## 遗留与下一步
- 用户本机 `git pull` 后需重启 admin-web，才能看到规格页的“同步规格”按钮（仍需 owner 账号）。
- 小程序权益页需在开发者工具里验证触底加载。
