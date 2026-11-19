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
- 接口文档必须写全，`scripts/check_api_docs.py` 在 CI 里检查，不全就不同步到 Apifox：
  - 每个接口：`tags`、固定的 `operation_id`（如 `photos_list`）、`summary`、`description`（说明用途、是否要登录、关键业务规则）、`response_description`。
  - 可能返回的错误都在 `responses` 里声明：`responses=errors_doc(ErrorCode.XXX, ...)`；业务里只抛 `AppError(ErrorCode.XXX)`，新错误码加在 `app/core/errors.py`。
  - 请求和响应都用 schemas.py 里的 Pydantic 模型，不返回裸字典；模型写 docstring。
  - 每个字段和每个路径、查询、请求头参数都写 `description`，有意义的给 `examples`；枚举值在 description 里逐个解释含义。
  - 说明用中文，写给前端看：这个字段是什么、单位、取值范围、什么时候为空。
- 生产环境关闭 `/docs` 和 `/openapi.json`。

## 数据库与迁移
- 只通过 Alembic 迁移改表结构；生成后先读脚本再执行。
- 已在其他环境执行过的迁移不改，新建一个。
- 外键写明 ondelete 并建索引；状态用 `check_in`（CHECK 约束），不用数据库枚举；能 NOT NULL 就 NOT NULL。
- 删列、改名分多次发布；数据修复用单独脚本。
- `scripts/seed_dev.py` 只能对名字以 `_dev` 结尾的库执行。

## 环境与部署
- 配置一律从环境变量读（`app/core/config.py`），代码里不写死地址、密码、环境判断以外的开关。
- `APP_ENV`：dev 本机 / test 自动化测试 / prod 服务器。
- 现在数据库在开发者 Mac 上；搬到服务器的步骤见 `docs/deploy.md`。不要让任何代码依赖“数据库在本机”。

## 安全（不可违反）
- `.env` 不提交；新增配置项同步写进 `.env.example`。
- 令牌只放请求头或 httpOnly Cookie，绝不放 URL。
- AppSecret、session_key 不下发前端。
- 日志不打印手机号、身份证号、令牌、密钥。
- 演示和测试数据只用假手机号、假身份证号。
- 数据库不对局域网开放。

## 工作方式
- **目标模式**：用户已授权全程自主推进，不需要中途确认。按 `docs/progress.md` 的顺序做；遇到真正无法替用户决定的事（花钱、资质、对外发布），先用 fake 模式绕过并记进 progress 的“需要用户提供”。
- **每项需求都要留记录**（换人、换电脑、换 AI 会话都靠它接上）：
  1. 开工前在 `docs/devlog/` 新建一篇（模板见 `docs/devlog/README.md`），写需求原文和拆解；
  2. 完成后补上方案、改动、验证、遗留，并更新 `docs/devlog/README.md` 目录和 `docs/progress.md`；
  3. 影响长期的设计决定写进 `docs/adr/`。
- **分工**：架构、跨模块设计、评审由高级模型（Opus）负责；按模块的实现可交给 Sonnet 子代理，每个子代理只改自己模块目录和对应测试目录，共享文件（`app/core`、`app/main.py`、`app/models/__init__.py`、迁移）由主会话统一修改。
- **验证靠 CI**：本地改完先 `ruff check` / `ruff format`；推送后看 GitHub Actions（迁移、`alembic check`、测试、接口文档检查）全部通过才算完成。
- **提交**：一次提交做一件事，提交信息说明“做了什么、为什么”。代码在 `/Users/mac/id-phone`（用户 Mac），推送到 GitHub `Tycalwayslove/id-phone-backend` 的 main。
- **用户本机才能做的事**（数据库在用户 Mac 上）：迁移、seed、启动服务。写成命令交给用户，输出存到 `backend/logs/`。
