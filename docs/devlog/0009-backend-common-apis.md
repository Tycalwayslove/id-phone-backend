# 0009 后端通用接口

- 日期：2026-11-19
- 状态：已完成
- 相关提交：1a41667（底座）、427c48a（六个模块）、c920d3c（回执与通知）、987a516（后台）、c03797a（修复）

## 需求
“现在开始后端开发吧，把常用接口都给补充好。然后再去梳理对接服务商相关的接口看要怎么弄。这个过程中还不牵扯前端设计，先把通用的接口设计好。”

## 拆解
1. 底座（主会话）：core 目录、统一错误码、会话与幂等表、外部服务适配层（全部带 fake）、测试与 CI。
2. 第一批模块（Sonnet 子代理并行）：auth + users、specs + photos、orders + entitlements。
3. 第二批：receipts + notify、admin。
4. 主会话评审、修 CI、补文档。

## 方案与决定
- 外部服务（微信登录、支付、存储、回执服务商、抠图）全部有 fake 模式，没有正式账号也能跑通整条链路，见 ADR 0003。
- 测试连真实 PostgreSQL（CI 起临时库），每个测试事务回滚隔离；`alembic check` 保证模型与迁移一致。
- 依赖变更由 CI 自动更新 uv.lock（AI 所在环境无法访问 PyPI）。
- 错误码集中在 `app/core/errors.py`，接口文档首页自动生成错误码表。
- 回执额度：提交时预占、成功时确认、驳回或失败时释放（驳回不扣次数）。

## 改动
- core：errors（错误码表）、deps（当前用户/后台账号/权限点/分页/幂等头）、security、idempotency、schemas、utils
- 表：auth_sessions、admin_sessions、idempotency_keys（迁移 b7c1d2e3f4a5）
- integrations：wechat、storage、payment、receipt_providers（全部 fake 可用）
- 模块与接口（约 64 个，见 Apifox 或 docs/api/openapi.json）：
  - auth/users：登录、退出、我的、改资料、绑手机号、注销
  - specs/photos：规格列表与详情；上传、照片、导出图（无权益带水印）、下载、删除
  - orders/entitlements：套餐、下单（幂等）、订单、取消、支付回调、模拟支付；权益列表与详情
  - receipts/notify：回执申请、驳回重提、取消、服务商回调、模拟结果、轮询函数；订阅消息模板与授权上报、通知任务
  - admin：后台登录（Cookie + CSRF）、用户/订单/回执查询、退款、套餐/规格管理、服务商开关、审计日志；`scripts/create_admin.py`
- CI：迁移 + alembic check + pytest + 接口文档检查 + Apifox 同步；接口快照自动提交到 `docs/api/openapi.json`；uv.lock、pnpm-lock 自动更新

## 验证
CI 全绿：129 个测试（含越权访问、幂等、回调去重、额度预占/确认/释放、驳回重提上限、退款撤销权益等关键路径）。

## 遗留
见 `docs/tasks/T002`～`T005`：定时任务、后端收尾项、回执服务商与微信支付正式接入。
