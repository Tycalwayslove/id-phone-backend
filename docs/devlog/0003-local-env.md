# 0003 本机开发环境与建库

- 日期：2026-11-18
- 状态：已完成

## 需求
“我前端熟练，后端 Python 和数据库不熟。后续建库、连库都让我手动操作，你给步骤我来实现。” 之后：“操作大概会了，你继续将数据库完善好，然后刷新 DBeaver 让我看到数据。”

## 拆解
1. 装 Postgres.app（不再用 brew 装第二份，避免端口冲突）、建角色和库 idphone_dev。
2. uv 建项目，FastAPI + SQLAlchemy + Alembic + pydantic-settings。
3. 第一轮手动建 channels、users 两张表，练习迁移流程。
4. 第二轮补全 28 张表并灌演示数据（seed_dev，只允许 *_dev 库）。

## 改动
`backend/` 骨架、两个迁移、`scripts/seed_dev.py`；手册见 Claude Doc「后端上手手册」。

## 验证
用户本机执行 revision / upgrade / seed，日志在 `backend/logs/`（不进 git），DBeaver 能看到数据。

## 遗留
AI 所在环境连不到用户 Mac 上的数据库，迁移和 seed 需要用户执行。
