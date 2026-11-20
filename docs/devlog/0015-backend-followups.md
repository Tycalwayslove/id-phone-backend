# 0015 后端收尾与后台前端适配（T003 + T010 第一段）

- 日期：2026-11-19
- 状态：已完成
- 相关提交：f64730e（T003）、60aaeac（T010 第一段）；PR #3

## 需求
任务单 T003 逐条处理各模块实现时记录的风险；T010 第一段：后台前端适配 T003 带来的接口变化。

## 拆解
1. 新增 `CONFLICT` 错误码；上传孤儿文件清理；全额退款联动回执与加购权益。
2. 后台退款幂等；订单已关闭却收到支付成功时自动退款。
3. 照片列表去 N+1；手机号检索不进 URL。
4. admin-web 跟进新接口，更新 `docs/api/openapi.json`。

## 方案与决定
- 新增错误码 `CONFLICT`（409），后台新建套餐/规格编码重复时返回。
- `photos.purge_orphan_uploads` 清理超时未被照片引用的原图。
- 全额退款确认后撤销订单及附属加购权益，取消未办结回执并释放额度。
- 退款幂等：请求体必填 `request_id`（UUID），派生确定性退款单号，同请求重试返回原记录，参数不一致返回 `IDEMPOTENCY_CONFLICT`；处理中退款占用可退余额。无需迁移。
- 订单已关闭却收到支付成功通知：自动全额退款并记审计日志。
- `entitlements.photo_access_many` 批量查权益。
- 评审决定（Claude）：手机号检索改为 `POST /api/v1/admin/users/search`，`GET /admin/users` 移除 phone 参数；前端退款 `request_id` 每次打开退款弹窗生成一次，同一次退款重试复用。

## 改动
- 后端：`app/core/errors.py`，admin、entitlements、orders、photos、receipts 模块的 router/schemas/service/repo，对应测试（admin、entitlements、orders、photos）。
- admin-web：`src/api/admin.ts`（用户查询走 POST）、`src/pages/orders.tsx`（退款带 request_id）。
- `docs/api/openapi.json` 同步更新。

## 验证
- 每条均有测试；PR #3 合入 main，CI 全绿。

## 遗留与下一步
- `docs/deploy.md` 中注明访问日志不记录查询串（T013）。
- T010 第二段在 T009 之后进行。
- `purge_orphan_uploads` 已由 runner 每轮调用（提交见 git log）。
- T010 第一段第 3 条（前端对 `CONFLICT` 的专门提示）本次提交未包含，后续补。
