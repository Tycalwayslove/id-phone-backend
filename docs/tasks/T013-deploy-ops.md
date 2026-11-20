# T013 部署与运维

- 状态：待开始
- 依赖：T002、T003；Wave 2

## 目标
让项目能在服务器上一条命令跑起来，并有备份与告警。

## 只允许改的文件
`deploy/**`、`backend/Dockerfile`、`docs/deploy.md`。

## 要求
1. compose 增加 nginx（worker 已由 T002 加）：静态托管 admin-web，SPA 路由回退，`/api` 同源代理。
2. nginx 访问日志不记查询串。
3. 定时备份数据库（脚本 + 保留策略 + 恢复步骤）。
4. 健康检查、告警说明写进 `docs/deploy.md`。
5. 数据库不对局域网开放；不在镜像或仓库里放密钥。

## 验收
- `docker compose config` 通过；文档步骤自上而下可执行。
