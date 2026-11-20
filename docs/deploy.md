# 部署与运维

这份手册适用于单机部署。Nginx 提供 HTTPS，托管运营后台并代理同源 `/api`、`/files/` 和 `/health`。PostgreSQL 18 和 API 的端口仅在容器网络可访问。数据库、应用文件和每日备份分别保存在 `pgdata`、`storage` 和宿主机的 `deploy/backups/`。

## 1. 准备服务器

安装 Docker Engine、Docker Compose 插件和 BuildKit。将域名解析到服务器，在安全组开放 TCP 80、443，并限制 SSH 来源。面向中国大陆的小程序按平台要求完成域名备案。

```bash
git clone https://github.com/Tycalwayslove/id-phone-backend.git
cd id-phone-backend/deploy
(umask 077; cp .env.example .env)
openssl rand -hex 24
openssl rand -hex 32
install -d -m 0700 backups
sudo install -d -m 0755 /var/www/idphone-acme
sudo install -d -m 0700 /etc/idphone/wxpay
```

将两条随机输出分别填入 `deploy/.env` 的 `POSTGRES_PASSWORD` 和 `SECRET_KEY`。迁移已有数据时使用原环境的 `SECRET_KEY`，以便解密已有字段。把 `NGINX_SERVER_NAME` 改为实际域名，并用 `id -u` 和 `id -g` 的输出填写 `BACKUP_UID` 和 `BACKUP_GID`。将应用凭证按上线清单写入 `.env`，证书和私钥放在仓库外。

当前分支的微信支付、回执和正式抠图适配器仍待接入。仅部署演示环境时，可显式设 `ALLOW_FAKE_IN_PROD=true`，并按演示需要将 `WECHAT_MODE`、`PAY_MODE`、`RECEIPT_MODE` 设为 `fake`。演示环境只使用测试数据，生产模式下 `/api/v1/dev/` 仍关闭。

## 2. 准备 HTTPS 证书

两种方式任选其一。以下示例域名为 `idphone.example.com`。Compose 将宿主机的 `NGINX_TLS_DIR` 只读挂载到容器的 `/etc/nginx/tls`，其余两个变量填容器内的完整路径。

### Certbot

域名解析生效后，在 Nginx 启动前用 Certbot 申请证书。首次申请时保持宿主机的 80 端口空闲。

```bash
sudo certbot certonly --standalone --cert-name idphone.example.com -d idphone.example.com
```

在 `deploy/.env` 中设置以下路径。挂载整个证书目录，确保 Certbot 的 `live` 链接可以访问 `archive` 内的证书和私钥。

```dotenv
NGINX_TLS_DIR=/etc/letsencrypt
NGINX_TLS_CERT_FILE=/etc/nginx/tls/live/idphone.example.com/fullchain.pem
NGINX_TLS_KEY_FILE=/etc/nginx/tls/live/idphone.example.com/privkey.pem
```

完成第 4 步并确认公网可访问后，用 Certbot 2.3 或以上版本将续期验证切换到 webroot。Nginx 已将 ACME 校验路径指向该目录。 [Certbot 续期配置](https://eff-certbot.readthedocs.io/en/stable/using.html#modifying-the-renewal-configuration-of-existing-certificates)

```bash
sudo certbot reconfigure --cert-name idphone.example.com --webroot -w /var/www/idphone-acme
```

确认宿主机的 Certbot 续期任务已启用。创建可执行的 `/etc/letsencrypt/renewal-hooks/deploy/idphone-nginx`，将下方路径替换为实际仓库目录。

```sh
#!/bin/sh
set -eu
cd /srv/id-phone-backend/deploy
docker compose exec -T nginx nginx -t
docker compose exec -T nginx nginx -s reload
```

### 云证书

在云证书控制台下载 Nginx 版 PEM 文件，将完整证书链和对应私钥放在 `NGINX_TLS_DIR` 指定的宿主机目录。用默认路径时，将两份文件分别存为 `/etc/idphone/tls/fullchain.pem` 和 `/etc/idphone/tls/privkey.pem`，将私钥权限设为 `0600`。

续期后替换挂载目录中的文件，在 `deploy/` 运行 `docker compose exec -T nginx nginx -t && docker compose exec -T nginx nginx -s reload`。若更改了路径变量，运行 `docker compose up -d nginx` 以重新生成配置。

## 3. 初始化数据库

后续命令均在服务器的 `deploy/` 运行。先检查配置、启动数据库并构建镜像。

```bash
docker compose config --quiet
docker compose up -d --wait db
docker compose build api worker nginx
```

空库直接执行迁移，跳过开发 seed。

```bash
docker compose run --rm --no-deps api alembic upgrade head
```

从 Mac 搬迁已有数据时，先停止旧环境写入。在旧仓库的 `backend/` 执行 `./scripts/db_backup.sh`，通过 SSH 将生成的归档传入服务器的 `deploy/backups/`，权限设为 `0600`。在新的空库中先执行下方的 [恢复步骤](#恢复到空库)，再继续启动服务。应用文件另行从原本地存储或 OSS 迁移，保持对象路径与数据库记录一致。

## 4. 启动与发布

```bash
docker compose up -d --wait
docker compose exec api python -m scripts.create_admin ops_owner owner
docker compose exec -T nginx nginx -t
curl -fsS https://idphone.example.com/health
curl -fsS -o /dev/null https://idphone.example.com/orders
curl -sS -o /dev/null -w '%{http_code}\n' https://idphone.example.com/docs
docker compose ps
```

管理员脚本交互输入密码。健康接口应返回 `{"status":"ok","database":"ok"}`，`/orders` 应返回 SPA 页面，`/docs` 应返回 404。浏览器打开后台并验证登录和同源 API 请求。

发布新版本前确认有可恢复的备份。检出目标版本后构建镜像，暂停写入，执行迁移，再启动服务。按顺序执行并在失败时停止。

```bash
docker compose build api worker nginx
docker compose stop nginx worker api backup
docker compose run --rm --no-deps api alembic upgrade head
docker compose up -d --wait
```

## 5. 备份与恢复

`backup` 服务启动时检查当天的归档，此后每天 UTC 02:00（北京时间 10:00）执行。它用 `pg_dump` 生成自定义格式归档，验证归档目录可读后发布为 `backups/idphone_prod-YYYY-MM-DD.dump`。同一 UTC 日已有归档时复用。服务每 15 分钟重试失败操作，保留最近 14 天的本机归档。

```bash
docker compose logs --tail=50 backup
docker compose exec -T backup bash /scripts/backup.sh
```

归档包含业务数据。每天核对备份状态，并限制备份目录和异地副本的读取权限。使用本地文件存储时，另行备份 `storage` 卷。将应用主密钥单独保存在可恢复的凭证管理系统中。

### 可选 OSS 异地备份

1. 创建私有 Bucket，为数据库备份设置独立前缀，例如 `postgres/idphone`。给上传账号授予该前缀所需的上传和分片上传权限，恢复账号单独授权读取。在 OSS 为该前缀设置 14 天过期、清理未完成分片的生命周期规则。 [OSS 上传权限](https://www.alibabacloud.com/help/en/oss/developer-reference/cp-upload-file)
2. 按服务器 CPU 架构下载 Linux 版 ossutil 2.x。将可执行文件 `ossutil` 和用 `ossutil config` 生成的 `.ossutilconfig` 一同放到仓库外的专用目录。配置文件使用 `0600`，目录和文件交给 `BACKUP_UID` 对应用户读取。 [ossutil 配置](https://www.alibabacloud.com/help/en/oss/developer-reference/configure-ossutil)
3. 在 `deploy/.env` 设置 `BACKUP_OSS_DIR=/etc/idphone/backup-oss` 和 `BACKUP_OSS_URI=oss://你的私有Bucket/postgres/idphone`。运行 `docker compose up -d backup` 并检查日志与 OSS 对象。

### 恢复到空库

从本地备份目录选取归档。若从 OSS 恢复，在有读取权限的机器上执行 `ossutil cp oss://你的私有Bucket/postgres/idphone/归档名.dump backups/归档名.dump`，并将归档权限设为 `0600`。

首次搬迁使用第 3 步的空库。恢复已有生产库时，先停止写入和每日备份，保留旧库并新建空库。以下旧库名应尚未使用。

```bash
docker compose stop nginx worker api backup
docker compose exec -T db psql -U idphone_app -d postgres -v ON_ERROR_STOP=1 \
  -c 'ALTER DATABASE idphone_prod RENAME TO idphone_pre_restore;'
docker compose exec -T db createdb -U idphone_app idphone_prod
```

用选定的归档路径替换示例路径。恢复使用单个事务，失败时回滚。每条命令成功后再执行下一条。

```bash
docker compose exec -T db pg_restore -U idphone_app -d idphone_prod \
  --no-owner --no-privileges --exit-on-error --single-transaction \
  < backups/idphone_prod-YYYY-MM-DD.dump
docker compose run --rm --no-deps api alembic current
docker compose run --rm --no-deps api alembic upgrade head
```

恢复配套的文件存储并确认主密钥一致，然后按第 4 步启动和验证。定期在独立的空库演练 `pg_restore`，将命令中的目标库换成演练库，核对 `alembic_version`、业务数据和关联文件。

## 6. 健康检查与告警

| 检查 | 告警条件 |
| --- | --- |
| 公网 HTTPS `GET /health` | 每分钟探测，连续 3 次超时、HTTP 非 200 或数据库状态异常就通知值班人 |
| Compose API 和 worker | 从宿主机监控容器退出、反复重启和 `unhealthy`。API 探针访问现有 `/health` 并检查数据库，worker 探针核对主进程的启动命令 |
| 定时任务异常 | 根据 worker 的定时任务错误日志告警，进程存活探针只检查进程 |
| PostgreSQL 备份 | 最新本机归档超过 26 小时，或启用 OSS 后云端归档超过 26 小时 |
| 主机和证书 | 监控磁盘空间和证书到期日，例如磁盘使用超过 80% 或证书距到期少于 14 天 |

用 `docker compose ps` 查看容器状态，用 `docker compose logs --tail=100 nginx api worker backup` 查看最近记录。将探针和告警接入服务器现有监控，并测试值班渠道能收到通知。Compose 的重启策略在进程退出时生效。`unhealthy` 需要监控发现并排查。

Nginx 访问日志使用 `$uri`，回调 `/api/v1/callbacks/` 和签名下载同样省略查询串。查询参数仍原样转发给 API。Nginx 关闭可能记录原始请求行的 HTTP 错误日志，保留主进程诊断。Uvicorn 关闭访问日志，Compose 强制 `DB_ECHO=false`。生产环境用 `docker compose config --quiet` 核对配置，避免将展开的配置和凭证写到终端日志。

## 上线检查清单

- [ ] DNS、备案、证书、80/443 和外网 `/health` 验证完成。数据库 5432 与 API 8000 均未映射到宿主机。
- [ ] `APP_ENV=prod` 且 `ALLOW_FAKE_IN_PROD=false`。启动校验会拒绝 `WECHAT_MODE`、`PAY_MODE`、`RECEIPT_MODE` 中的任一 `fake` 值及默认 `SECRET_KEY`。`ALLOW_FAKE_IN_PROD=true` 仅供隔离的演示环境。
- [ ] 填写 `POSTGRES_PASSWORD` 和至少 32 字符的 `SECRET_KEY`。正式小程序填写 `WX_MINI_APP_ID`、`WX_MINI_APP_SECRET`。正式支付填写商户号、APIv3 密钥、证书序列号、商户私钥路径、平台证书路径。填写已启用回执服务商的 AppKey 和 AppSecret。若应用文件使用 OSS，填写其 Endpoint、Bucket 和访问凭证。
- [ ] 小程序生产构建设置 `TARO_APP_API_BASE=https://实际域名` 和 `TARO_APP_FAKE_PAY=0`。小程序后台配置 HTTPS request 合法域名，并按使用的接口配置 uploadFile、downloadFile 合法域名，包含实际签名下载域名（如应用文件的 OSS 域名）。
- [ ] 从公网确认微信支付 `/api/v1/callbacks/wxpay` 和回执 `/api/v1/callbacks/receipt/<provider_code>` 的 HTTPS POST 可达，并通过平台正式联调验证签名和回执。确认支付、回执和正式抠图适配器均已合入，当前 worktree 的部署健康检查只验证服务和数据库。
- [ ] 数据库迁移成功，后台登录与同源 API 正常，首次备份和空库恢复演练通过，告警通知已验证。
