# T030 运营后台列表改为页码分页

- 状态：进行中
- 决策：先读 `docs/adr/0008-admin-offset-pagination.md`。用户原话：“运营后台现在是直接加载更多来加载下一页的数据，我需要那种正常管理后台的分页组件，可以直接跳转到指定页，以及自己去选择每页多少数据”。

## 只允许改的文件
`backend/app/core/pagination.py`、`backend/app/core/deps.py`、`backend/app/modules/admin/`、各模块里**只给后台用**的列表函数（如 `receipts` 的 `list_admin_applications`、`photos` 的后台查询；改动写进 `CONTRACTS.md`）、`backend/app/modules/CONTRACTS.md`、`backend/tests/`、`admin-web/src/`、`docs/api/openapi.json`（生成）。**不改 C 端游标分页接口和小程序。**

## 要求
### 后端
1. `core/pagination.py` 新增：`OffsetPageParams`（`page>=1`、`page_size` 只允许 10/20/50/100，默认 20，`offset` 属性）、请求体用的 `OffsetPageIn`、`deps.Paging` 查询参数依赖（description 写全）、`offset_page_model(item, name, order=...)` 返回 `{items, total, page, page_size}`（字段 description 写全）、`paginate(db, stmt, params) -> (rows, total)`（对原查询做 `select(func.count()).select_from(stmt.order_by(None).subquery())`，再 `offset/limit`）。保留游标分页的现有工具不动。
2. 以下后台列表全部改为页码分页，筛选参数不变，排序固定且含唯一键：`GET /admin/users`、`POST /admin/users/search`、`/admin/client-apps`、`/admin/photos`、`/admin/orders`、`/admin/receipt-applications`、`/admin/specs`、`/admin/provider-specs`、`/admin/route-rules`、`/admin/notify-tasks`、`/admin/admin-users`、`/admin/audit-logs`。返回模型改名不改语义（如仍叫 `AdminUserPage`，结构变为页码版）。
3. `page` 超过最后一页时返回空 `items` 和正确的 `total`（不报错）。
4. 测试：公共工具单测（count 正确、offset、page_size 校验 422）；每个接口至少一条“第 2 页 + total”断言；后台接口数断言不变。

### 运营后台前端
5. `components/ui.tsx`：用通用 `PagedTable`（antd `Table` 的 `pagination`：`showTotal` 显示“共 N 条”、`showSizeChanger` 10/20/50/100、`showQuickJumper`）和 `usePagedList(resource, fetchPage, filters)` 替换 `CursorTable`/`useCursorList`；`page`、`page_size` 同步到网址查询参数（刷新不丢），筛选变化回到第 1 页；数据加载中保留上一页内容并显示加载态（`placeholderData: keepPreviousData`）。
6. 10 个页面全部替换：`administrators`、`audit`、`client-apps`、`notifications`、`orders`、`photos`（网格展示也要有同样的分页条）、`providers`（服务商详情里的规格映射与路由规则两个表）、`receipts`、`specs`、`users`。删除不再使用的 `CursorTable`/`useCursorList`。
7. 一个页面里有多个分页表格时（如服务商详情），各自的网址参数加前缀避免冲突，或只把主表放进网址。

## 协作约束（重要）
只改工作区文件，**不要 git commit、不要 bundle、不要输出 base64**；没有网络。改完跑 ruff、能跑的测试、admin-web 的 `gen:api`、typecheck、build。最后简短报告。
