# 0021 后台接口增强（T009）

- 日期：2026-11-19
- 状态：已完成
- 相关提交：8f0f3d0、935708a（看板修复）；PR #6

## 需求
任务单 T009：补看板、通知任务、路由规则、管理员账号与角色接口。

## 拆解
1. 看板 `GET /api/v1/admin/stats/overview`。
2. 通知任务列表（游标分页、状态筛选）。
3. `provider_specs`、`route_rules` 增删改。
4. 管理员列表、新建、停用、改角色、重置密码。
5. 审计、权限点、文档。

## 方案与决定
- 共 13 个新接口；写操作同事务记审计；重复编码用 `CONFLICT`。
- 临时密码只在响应中出现一次，首次登录须改密。
- 不能停用或降级自己；保护最后一个 owner。
- 新增权限点 `stats:read`、`notify:read`、`admin:read`、`admin:write`。
- CI 发现看板 bug：`dict(Result)` 因 Result 有 `keys()` 被当成映射，修复为先 `.all()` 再转 dict（935708a）。
- 无需迁移。

## 改动
- `backend/app/modules/admin/{repo,router,schemas,service}.py`、`backend/app/core/deps.py`（权限点）。
- 测试：`backend/tests/admin/test_admin_plus.py`。

## 验证
- CI 全绿（273 个测试、接口文档检查）；`docs/api/openapi.json` 已更新。

## 遗留与下一步
- T010 第二段（admin-web 对接这些接口）已交 Codex，Wave 3 进行中。
