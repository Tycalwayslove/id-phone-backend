# AGENTS.md（给 Codex / ChatGPT 等编码代理）

本项目的完整规则在 `CLAUDE.md`，**开始任何工作前先完整读一遍 `CLAUDE.md` 和 `docs/README.md`**，两份规则对所有 AI 一样有效。

## 分工

- 架构、跨模块决策、任务拆解由 Claude（Opus）负责，写在 `docs/tasks/` 里。
- 编码代理按 `docs/tasks/` 里的任务单实现。任务单写了“只允许改的文件”，不要越界；需要改共享文件（`backend/app/core/`、`backend/app/main.py`、`backend/app/models/`、迁移、CI）时，在任务结束报告里提出，由 Claude 决定。

## 做完一个任务必须

1. 后端：`cd backend && uv run ruff check . --fix && uv run ruff format .`；能连数据库就跑 `uv run pytest`。前端：`pnpm run gen:api && pnpm run typecheck && pnpm run build`。
2. 在 `docs/devlog/` 写一篇（模板见 `docs/devlog/README.md`），更新 `docs/devlog/README.md` 目录和 `docs/progress.md`，把任务单状态改为“已完成”。
3. 提交信息写清做了什么、为什么；推送后确认 GitHub Actions 全绿（迁移、`alembic check`、测试、接口文档检查、前端构建）。

## 关键约定速查

- 后端分层：router → service → repo → models；外部服务只走 `backend/app/integrations`；跨模块只调 `backend/app/modules/CONTRACTS.md` 里的函数。
- 错误：业务里只抛 `AppError(ErrorCode.X)`；接口文档必须写全（中文 description、examples、errors_doc），CI 会检查。
- 前端：接口类型从 `docs/api/openapi.json` 生成，不手写；请求统一走 `src/api/`。
- 安全：令牌不进 URL；手机号、身份证号不进日志；`.env` 不提交。
