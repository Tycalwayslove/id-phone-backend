# 0014 定时任务 worker（T002）

- 日期：2026-11-19
- 状态：已完成
- 相关提交：417d56d、733e9cf（配置项）；PR #1

## 需求
任务单 T002：把已写好的后台处理函数（回执轮询 `poll_due`、通知发送 `send_due`）定时跑起来，并补上关闭过期订单、到期提醒；不引入 Celery。

## 拆解
1. 新建 `backend/app/workers/runner.py` 循环进程，每轮依次执行四项任务。
2. orders 新增 `close_expired`，entitlements 新增 `create_expiration_reminders`，notify 新增 `create_task_once`。
3. docker-compose 增加 `worker` 服务。
4. 每个任务函数写单测。

## 方案与决定
- `python -m app.workers.runner`，每 60 秒一轮（间隔来自配置 `WORKER_INTERVAL_SECONDS`），依次执行：回执轮询、通知发送、关闭过期待支付订单、生成保管期到期提醒（剩 7 天、1 天各一次）。
- 每项独立回滚、出错记日志后继续下一项；PostgreSQL advisory lock 保证多实例只有一个在跑；SIGTERM 优雅退出。
- 评审决定（Claude）：`notify.create_task_once` 新增，依赖已有的 NULLS NOT DISTINCT 唯一索引去重，同一权益同一档只建一次；其中 `step` 表示提醒档位（7 天 / 1 天），逐级升级则按 channel 区分（见 T008）。
- 配置项 `WORKER_INTERVAL_SECONDS` 属共享文件，由 Claude 在提交 733e9cf 中统一加入。

## 改动
- 新增 `backend/app/workers/__init__.py`、`runner.py`，测试 `backend/tests/workers/test_workers.py`。
- `backend/app/modules/{entitlements,notify,orders}/` 的 repo、service 各增加对应函数；`backend/app/modules/CONTRACTS.md` 补一行。
- `deploy/docker-compose.yml` 增加 `worker` 服务（与 api 共用镜像和存储卷）。

## 验证
- 单测覆盖：过期订单被关闭、到期提醒不重复建。
- ruff 与 CI 由 Claude 执行；PR #1 合入 main，CI 全绿。

## 遗留与下一步
- T003 的 `photos.purge_orphan_uploads` 已挂进 runner（每轮清理上传超过 24 小时未建照片的原图）。
- T008 在此基础上实现真实通知通道与逐级升级。
