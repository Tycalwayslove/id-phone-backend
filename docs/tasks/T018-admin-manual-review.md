# T018 后台“需人工核对”处理

- 状态：进行中（Codex，Wave 4）
- 依赖：T016（超时标记 `manual_review_required`）、T010

## 目标
回执超时无结果（真实通道 2 小时）被标记为需人工核对后，运营能在后台查看并处理。

## 只允许改的文件
`backend/app/modules/admin/`、`backend/app/modules/receipts/`（只加后台所需 service 函数）、对应 `backend/tests/`、`admin-web/src/`。共享文件（`core/errors.py`、迁移、`CONTRACTS.md`）需要改动时写进报告，由主会话合入。

## 要求
1. 后台回执列表/详情增加“是否需人工核对”字段（来自 attempt 的 `manual_review_required` 标记），列表支持按该条件筛选。
2. 新增“标记已核对”接口：走 receipts 状态机（不绕过状态迁移校验，已终态不可改），写审计日志，需相应权限点，支持幂等；接口文档写全。
3. admin-web 回执页：列表显示“需人工核对”标签；详情提供处理弹窗（选择核对结果、填备注），提交后刷新。按权限显示按钮。

## 验收
- 后端测试覆盖筛选、标记成功、终态拒绝、审计记录；`pnpm run gen:api && pnpm run typecheck && pnpm run build` 通过；CI 全绿。
