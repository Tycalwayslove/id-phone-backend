# T009 后台接口增强

- 状态：待开始
- 依赖：T003；Wave 2

## 目标
补运营后台缺的接口：数据看板、通知任务、路由规则、管理员账号与角色。

## 只允许改的文件
`backend/app/modules/admin/`、`backend/tests/admin/`。

## 要求
1. `GET /api/v1/admin/stats/overview`：看板（用户数、订单数、实付总额 `_fen`、回执各状态数等）。
2. 通知任务列表（游标分页、按状态筛选）。
3. `provider_specs` 与 `route_rules` 的增删改。
4. 管理员账号与角色管理（新建、停用、改角色、重置密码）。
5. 所有写操作记审计日志；按权限点控制；重复编码用 `CONFLICT`。
6. 接口文档按 CLAUDE.md 写全（`errors_doc`、中文 description、examples），`scripts/check_api_docs.py` 通过。

## 验收
- 每个接口有权限、成功、失败测试。
- CI 全绿；`docs/api/openapi.json` 由 CI 机器人更新。
