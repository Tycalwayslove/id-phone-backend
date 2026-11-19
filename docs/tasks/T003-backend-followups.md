# T003 后端收尾

- 状态：待开始

来自各模块实现时记录的风险，逐条处理：

1. 新增错误码 `CONFLICT`（409，“数据已存在”），后台新建套餐/规格编码重复时改用它（现在是 VALIDATION_ERROR）。改 `app/core/errors.py` 和 admin 模块。
2. 上传了但没创建照片的文件（kind=original、没有被 photos 引用、创建超过 24 小时）定期清理：photos 模块新增 `purge_orphan_uploads(db, older_than)`，由 T002 的 runner 调用。
3. 全额退款时：取消该订单权益下办理中的回执申请（调用 receipts.cancel_application），附属加购权益一起撤销。
4. 后台退款支持幂等：请求体增加 `request_id`（前端生成 UUID），同一 request_id 只退一次（可复用 idempotency_keys 表，user_id 改为可空需要迁移——先在报告里提出方案）。
5. 订单已关闭却收到支付成功通知：自动发起全额退款并记审计。
6. 照片列表每张照片单独查权益（N+1）：entitlements 新增批量函数 `photo_access_many(db, user_id, photo_ids)`。
7. 后台按手机号筛选用户时手机号在 URL 查询串里，会进 Uvicorn/Nginx 访问日志：改为不在 URL 中出现（如 `POST /api/v1/admin/users/search`，或前端只传手机号哈希），并在 `docs/deploy.md` 注明访问日志格式不记录查询串。（来自 0012 评审）

每条都要有测试。只允许改涉及到的模块目录和对应 tests 目录；`app/core/errors.py` 本任务允许改。
