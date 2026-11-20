# ADR 0005 多代理分工与合并规则

- 状态：已采纳（2026-11-19）

## 决定
- **Opus**：全局规划、架构、评审与合并，写任务单与 ADR。
- **Codex**：每个任务在独立 git worktree 里按任务单实现。
- **Sonnet**：写文档、改项目说明类文件。
- 任务单“只允许改的文件”互不重叠，从根上避免冲突。
- 共享文件（`backend/app/core/`、`app/main.py`、`app/models/__init__.py`、`.env.example`、`CONTRACTS.md`、CI）由主会话线性合入；任务分支把需求写进报告。
- 迁移只能有一个 head：需要迁移的任务提出方案，由主会话按顺序建迁移。
- `docs/api/openapi.json` 由 CI 生成，任务分支按合入顺序 rebase，冲突以最新生成为准。
- 任务按依赖分波次推进（见 `docs/tasks/README.md`）。

## 理由
目标是前后端快速完成；并行实施能缩短周期，范围隔离与线性合入保证主线稳定。

## 代价
主会话成为合并瓶颈；worktree 之间的接口约定要靠任务单和 `CONTRACTS.md` 写清；依赖任务必须等前序合入。
