# 本机运行

## 需要的软件

- Postgres.app（PostgreSQL 18），不要再用 brew 装一份，会抢 5432 端口
- uv（Python 包管理），Python 3.14 由 uv 自动安装
- DBeaver（看数据，可选）
- Apifox（看接口文档，可选）

## 第一次运行

```bash
cd backend
cp .env.example .env          # 填上本机数据库密码
uv sync                       # 安装依赖
uv run alembic upgrade head   # 建表
uv run python -m scripts.seed_dev   # 灌演示数据（只对 *_dev 库生效）
uv run uvicorn app.main:app --reload
```

打开 <http://localhost:8000/docs> 看接口并直接调试。

## 用假服务联调（默认）

`.env` 里不配置微信、支付、回执服务商时，全部走 fake 模式：

| 场景 | 怎么做 |
|---|---|
| 小程序登录 | `POST /api/v1/auth/wechat-mini/login`，code 填 `dev:alice`，固定得到 alice 这个用户 |
| 绑定手机号 | code 填 `phone:13800001234` |
| 支付 | 下单返回 `mode: fake`，再调 `POST /api/v1/dev/orders/{order_no}/simulate-paid` |
| 回执结果 | 调 `POST /api/v1/dev/receipt-attempts/...` 模拟成功或驳回（见接口文档“联调”目录） |

## 测试

```bash
createdb idphone_test                       # 第一次：建测试库
DATABASE_URL=postgresql+psycopg://idphone_app:密码@localhost:5432/idphone_test uv run alembic upgrade head
DATABASE_URL=postgresql+psycopg://idphone_app:密码@localhost:5432/idphone_test uv run pytest
```

推送到 GitHub 后，CI 会在临时数据库上自动跑一遍，不需要本机跑。

## 常用命令

| 做什么 | 命令 |
|---|---|
| 代码检查和格式化 | `uv run ruff check . --fix && uv run ruff format .` |
| 改了模型后生成迁移 | `uv run alembic revision --autogenerate -m "说明"`，生成后先读再执行 |
| 检查模型和迁移是否一致 | `uv run alembic check` |
| 检查接口文档是否写全 | `uv run python -m scripts.check_api_docs` |
| 备份本机数据库 | `./scripts/db_backup.sh` |

## 用 Claude Code + Codex 协作（省 Claude 额度）

在 Mac 终端里用 Claude Code 当“决策者”，通过 OpenAI 官方插件 [codex-plugin-cc](https://github.com/openai/codex-plugin-cc) 把编码任务交给 Codex（用 ChatGPT 账号额度）。插件只能在本机运行。

一次性安装：

```bash
npm install -g @openai/codex     # 需要 Node 18.18+
codex login                       # 用 ChatGPT 账号登录
cd /Users/mac/id-phone && claude  # 在项目目录启动 Claude Code
```

在 Claude Code 里：

```
/plugin marketplace add openai/codex-plugin-cc
/plugin install codex@openai-codex
/reload-plugins
/codex:setup
```

日常用法：

- 交任务：`/codex:rescue --background 按 docs/tasks/T001-admin-web.md 完成，遵守 AGENTS.md`
- 看进度和结果：`/codex:status`、`/codex:result`
- 让 Codex 审查改动：`/codex:review --background`
- 不要打开插件的 review gate（自动循环审查），很快耗光额度。
