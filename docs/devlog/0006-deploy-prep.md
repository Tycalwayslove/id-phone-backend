# 0006 为迁到服务器做准备

- 日期：2026-11-19
- 状态：已完成
- 相关提交：87f3c8c

## 需求
“数据库暂时放我电脑上，做好迁移准备工作，后续我会买服务器，然后迁移。”

## 改动
- 配置全部走环境变量，新增 APP_ENV、DB_ECHO；生产环境关闭接口文档页面。
- 连接池 pool_pre_ping；alembic 转义密码中的 %。
- `scripts/db_backup.sh`、`db_restore.sh`（恢复前要求输入库名确认，单事务）。
- `backend/Dockerfile`、`deploy/docker-compose.yml`、`docs/deploy.md`（搬家手册与检查清单）。

## 遗留
Dockerfile 和 compose 未在真实 Docker 上构建过，第一次部署时验证。
