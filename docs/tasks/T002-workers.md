# T002 定时任务

- 状态：待开始

## 目标
把已写好的后台处理函数定时跑起来。

## 已有函数
- `app.modules.receipts.poller.poll_due(db, limit=50)`：轮询服务商结果
- `app.modules.notify.service.send_due(db, limit=100)`：发送到期的通知任务

## 要做
1. 新建 `backend/app/workers/runner.py`：一个简单的循环进程（不引入 Celery），每 60 秒依次执行：回执轮询、通知发送、关闭过期未支付订单（orders 模块新增 `close_expired(db, limit)`）、生成到期提醒（保管期还剩 7 天和 1 天时给用户建 `entitlement_expiring` 通知任务，同一权益同一档只建一次）。每项独立 try/except，出错记日志继续下一项。用 PostgreSQL advisory lock 保证多实例只有一个在跑。
2. `deploy/docker-compose.yml` 增加 `worker` 服务（同一镜像，命令 `python -m app.workers.runner`）。这是共享文件，按 AGENTS.md 先在报告里提出，由 Claude 合入。
3. 测试：每个任务函数单测（过期订单被关闭、到期提醒不重复建）。

## 只允许改的文件
`backend/app/workers/`、`backend/app/modules/orders/service.py`（只新增 close_expired）、`backend/app/modules/entitlements/service.py`（只新增提醒相关函数）、`backend/tests/workers/`。
