# 部署与数据库迁移手册

现在数据库在开发者的 Mac 上（Postgres.app，库名 idphone_dev）。这份手册说明以后买了服务器怎么搬过去。

## 已经做好的准备

| 准备 | 作用 |
|---|---|
| 所有配置走环境变量（`backend/.env`） | 换环境只改配置，不改代码 |
| 表结构全部由 Alembic 迁移管理 | 服务器上一条命令建出完全相同的表 |
| `scripts/seed_dev.py` 只能写 `_dev` 结尾的库 | 演示数据不会进生产库 |
| `scripts/db_backup.sh` / `db_restore.sh` | 有真实数据后用来备份和搬家 |
| `backend/Dockerfile` + `deploy/docker-compose.yml` | 服务器上用 Docker 跑，环境和本机一致 |
| `APP_ENV=prod` 时关闭 `/docs` 和 `/openapi.json` | 生产环境不暴露接口清单 |

## 现在要遵守的

1. 不在 DBeaver 里手工改表结构，一律走迁移。否则服务器上建出来的表和本机不一样。
2. 本机库里只放演示数据。开始有真实用户数据之前，应该已经搬到服务器。
3. 如果真实数据不得不先放在本机，每天跑一次 `./scripts/db_backup.sh`，并把备份文件另存一份。

## 选服务器

- 小程序要求接口域名已备案并且用 HTTPS，所以买国内云服务器，先把域名备案办下来（需要时间）。
- 数据库两种放法：
  - **同机 Docker**：便宜，就是本目录的 compose 文件。备份要自己做。
  - **云数据库 RDS PostgreSQL**：多花钱，自动备份、可按时间点恢复。数据涉及身份证号和照片，用户量起来后建议换成这种。
- PostgreSQL 版本保持 18，和本机一致。

## 搬家步骤

### 1. 服务器准备

```bash
# 服务器上：装好 Docker 后
git clone https://github.com/Tycalwayslove/id-phone-backend.git
cd id-phone-backend/deploy
cp .env.example .env
openssl rand -hex 24          # 把输出填进 .env 的 POSTGRES_PASSWORD
docker compose up -d db
```

### 2. 建表或搬数据（二选一）

**A. 还没有真实数据（预期的情况）**：直接在空库上执行迁移，不跑 seed。

```bash
docker compose run --rm api alembic upgrade head
```

**B. 本机已经有真实数据**：先停止写入，再备份、上传、恢复。

```bash
# 本机
cd backend && ./scripts/db_backup.sh
scp backups/<文件名>.dump <服务器>:~/id-phone-backend/deploy/backups/

# 服务器
cd ~/id-phone-backend/deploy
docker compose exec -T db pg_restore -U idphone_app -d idphone_prod \
  --no-owner --no-privileges --exit-on-error --single-transaction /backups/<文件名>.dump
docker compose run --rm api alembic current    # 应该显示和本机相同的版本号
docker compose run --rm api alembic upgrade head
```

### 3. 启动并检查

```bash
docker compose up -d api
curl http://127.0.0.1:8000/health    # 应返回 {"status":"ok","database":"ok"}
```

### 4. 对外开放

- 用 Nginx 或 Caddy 配 HTTPS，反向代理到 `127.0.0.1:8000`。
- 小程序后台把服务器域名加到“request 合法域名”。
- 数据库端口始终不对公网开放。

### 5. 之后

- 本机 `backend/.env` 继续指向 idphone_dev，用于开发；生产数据只在服务器。
- 服务器上每天定时备份，并把备份传到对象存储，保留至少 7 天。
- 每次发布：拉代码 → `docker compose build api` → `docker compose run --rm api alembic upgrade head` → `docker compose up -d api`。以后由 GitHub Actions 自动做。

## 搬家前检查清单

- [ ] 域名已备案，HTTPS 证书就绪
- [ ] `deploy/.env` 里是新生成的随机密码，没有复用本机密码
- [ ] 服务器安全组只开放 80 / 443 和 SSH
- [ ] `alembic upgrade head` 在服务器上执行成功
- [ ] `/health` 返回正常，`/docs` 返回 404
- [ ] 第一次服务器备份已生成，并试过恢复
