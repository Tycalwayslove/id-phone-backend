# 0011 改用 Codex/ChatGPT 编码、Claude 决策

- 日期：2026-11-19
- 状态：已完成

## 需求
“我 Claude 的额度不够，但是 ChatGPT 额度足够，能不能你用来决策，跑代码这些让 ChatGPT 来写？”

## 方案与决定
- Claude 无法直接调用 ChatGPT。改为“任务单交接”：Claude 负责拆解和决策，把任务写成 `docs/tasks/Txxx-*.md`（目标、只允许改的文件、规则、验收标准）；用户用 Codex（OpenAI 的编码代理，读取仓库根目录 `AGENTS.md`）或 ChatGPT 按任务单实现。
- 新增 `AGENTS.md`：指向 `CLAUDE.md` 的全部规则，并写明编码代理的边界（不改共享文件，做完写 devlog、看 CI）。
- 验收靠 CI：迁移、alembic check、测试、接口文档检查、前端构建全绿才算完成；Claude 只在需要决策或评审时介入，节省额度。

## 改动
`AGENTS.md`、`docs/tasks/`（T001～T005）。
