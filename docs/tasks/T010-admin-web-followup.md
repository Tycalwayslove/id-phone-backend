# T010 后台前端跟进

- 状态：第一段已完成（用户检索 POST、退款 request_id；CONFLICT 由编辑弹窗直接显示后端返回的“数据已存在”）；第二段待 T009
- 依赖：第一段依赖 T003；第二段依赖 T009

## 目标
让 admin-web 跟上后端变化，并补新页面。

## 只允许改的文件
`admin-web/` 下的文件。

## 要求
**第一段（T003 合入后立即做，否则 typecheck 会失败）**
1. 手机号检索改为 `POST /api/v1/admin/users/search`，手机号不再出现在 URL。
2. 退款请求带 `request_id`（前端生成 UUID）。
3. 处理 `CONFLICT`（409）提示“数据已存在”。

**第二段（T009 合入后）**
4. 新增页面：数据看板、通知任务、路由规则（含 provider_specs）、管理员账号与角色。
5. 菜单与按钮按 `permissions` 显示。

## 验收
- `pnpm run gen:api && pnpm run typecheck && pnpm run build` 通过，CI 全绿。
