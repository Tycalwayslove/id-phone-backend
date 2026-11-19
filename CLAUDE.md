# 项目规则（证件照 + 回执）

每次开始工作前先读本文件。完整说明见 Claude Doc「架构与项目规范」「数据库设计」「登录与权限设计」。

## 技术栈
Python 3.14 · uv · FastAPI · SQLAlchemy 2（同步）· Alembic · PostgreSQL 18 · psycopg 3 · pydantic-settings

## 目录与分层
- `backend/app/core/`：配置、数据库会话、日志、令牌、统一错误
- `backend/app/models/`：ORM 模型，按域分文件
- `backend/app/modules/<模块>/{router,schemas,service,repo}.py`：每个业务模块结构相同
- `backend/app/integrations/`：回执服务商、微信、OSS、短信的适配器
- `backend/app/workers/`：后台任务
- 规则：
  1. router 只做“解析参数 → 调 service → 返回”，不写 SQL、不写业务判断。
  2. service 不碰 HTTP 请求对象；事务在 service 里开和提交。
  3. C 端 repo 查询函数第一个参数是当前用户 ID，查不到当作不存在（404）。
  4. 模块之间只调对方的 service，不直接碰对方的 repo 和表。
  5. 外部服务只通过 integrations 的统一接口调用。

## 接口
- 前缀 `/api/v1/`；资源用复数。
- 错误统一为 `{"code": "...", "message": "..."}`，错误码集中定义。
- 金额用整数分，字段名带 `_fen`；时间用 timestamptz，库里一律 UTC。
- 列表用游标分页，limit 上限 100。
- 下单、提交回执等接口支持 `Idempotency-Key` 请求头。
- 每个接口写 `summary`、`tags`、固定的 `operation_id`；请求和响应都用 schemas.py 里的模型，并在 `responses` 里声明错误码。
- 生产环境关闭 `/docs` 和 `/openapi.json`。

## 数据库与迁移
- 只通过 Alembic 迁移改表结构；生成后先读脚本再执行。
- 已在其他环境执行过的迁移不改，新建一个。
- 外键写明 ondelete 并建索引；状态用 `check_in`（CHECK 约束），不用数据库枚举；能 NOT NULL 就 NOT NULL。
- 删列、改名分多次发布；数据修复用单独脚本。
- `scripts/seed_dev.py` 只能对名字以 `_dev` 结尾的库执行。

## 安全（不可违反）
- `.env` 不提交；新增配置项同步写进 `.env.example`。
- 令牌只放请求头或 httpOnly Cookie，绝不放 URL。
- AppSecret、session_key 不下发前端。
- 日志不打印手机号、身份证号、令牌、密钥。
- 演示和测试数据只用假手机号、假身份证号。
- 数据库不对局域网开放。

## 工作方式
1. 先给设计：动哪些模块、哪些表、新增哪些接口和错误码；确认后再写代码。
2. 代码和测试一起写；关键路径（扣额度、回调幂等、驳回重提、越权访问）必须有测试。
3. 需要执行的命令（迁移、seed、启动服务）写成步骤交给用户在本机运行，输出存到 `backend/logs/`。
4. 重要设计决定记到 `docs/adr/`。
