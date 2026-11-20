# 0022 部署与运维（T013）

- 日期：2026-11-19
- 状态：已完成（待服务器实测）
- 相关提交：7783b09；PR #6

## 需求
任务单 T013：服务器上一条命令跑起来，并有备份与告警。

## 拆解
1. nginx 托管 admin-web，同源代理 `/api`。
2. admin-web 镜像。
3. 数据库定时备份、保留、恢复。
4. 健康检查、告警、上线检查清单。

## 方案与决定
- nginx 托管 admin-web，SPA 回退；访问日志用 `$uri`，不记查询串；关闭 uvicorn 访问日志。
- admin-web 多阶段镜像。
- `backup` 服务每日 `pg_dump`，保留 14 天，可选上传 OSS。
- 数据库 5432 与 API 8000 不映射到宿主机。
- 无需迁移。

## 改动
- `deploy/docker-compose.yml`、`deploy/nginx/{nginx.conf,site.conf.template}`、`deploy/admin-web.Dockerfile`（及 dockerignore）、`deploy/backup/{backup.sh,run-daily.sh}`、`deploy/.env.example`、`backend/Dockerfile`。
- `docs/deploy.md`：证书、初始化、发布、备份与恢复、健康检查与告警、上线检查清单。

## 验证
- CI 全绿；`docker compose config` 通过。尚未在真实服务器执行。

## 遗留与下一步
- 需要服务器、域名、备案、HTTPS 证书；照 `docs/deploy.md` 的“上线检查清单”逐项验证（含首次备份与空库恢复演练、告警验证）。
- 清单要求 `APP_ENV=prod` 且不得有 fake 模式，需先补齐各服务商账号。
