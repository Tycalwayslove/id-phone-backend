# 0029 后台“需人工核对”处理（T018）

- 日期：2026-11-19
- 状态：已完成
- 相关提交：ef836a1、a2dc131；PR #8

## 需求
任务单 T018：回执超时无结果被标记为需人工核对（T016）后，运营能在后台查看并处理。

## 拆解
1. 后台回执列表/详情输出 `manual_review_required`，列表支持 `manual_review=true` 筛选。
2. 新增人工核对接口，走 receipts 状态机，写审计日志。
3. admin-web 回执页显示标签与处理弹窗。

## 方案与决定
- 新接口 `POST /admin/receipt-applications/{app_no}/manual-review`，按现有状态机登记 `completed` / `rejected` / `failed` 结论，不绕过状态迁移校验。
- admin 只调 receipts 的 service（receipts 新增后台所需函数与查询），遵守“模块之间只调对方 service”。

## 改动
- 后端：`modules/admin/{router,schemas,service,repo}.py`、`modules/receipts/{repo,service}.py`、`modules/CONTRACTS.md`、`docs/api/openapi.json`。
- 前端：`admin-web/src/{api/admin.ts,format.ts,pages/receipts.tsx}`。
- 测试：`tests/admin/test_admin.py`、新增 `tests/receipts/test_manual_review_units.py`。

## 验证
- CI 首次发现后台接口数断言失败：`test_admin.py` 里断言后台接口总数为 34，T018 新增一个接口后实为 35。a2dc131 把断言改为 35，随后 PR #8 CI 全绿（315 个测试、两个前端构建、Apifox 同步）。
- 教训：新增接口要同步这个计数断言。

## 遗留与下一步
- 需要后台账号联调实际操作流程。
