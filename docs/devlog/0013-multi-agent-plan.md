# 0013 多代理并行规划

- 日期：2026-11-19
- 状态：已完成
- 相关提交：2233d4d（规划文档）；合入的 PR：#1（T002）、#2（T006+T007）、#3（T003+T010 第一段）、#4（T011）、#5（T004）、#6（Wave 2）、#7（Wave 3）、#8（Wave 4）

## 需求
“我希望你帮我多开几个子agent，用opus5.5来做全局规划和架构，然后具体的代码实施分配给codex来做，然后用sonnet5.5 来写文档和项目修改。如果可以，我希望你引入superpower skill，统筹全局的需求。最后我需要的是：前后端都快速实施完毕。”

## 拆解
1. Opus 做差距分析与任务拆解（本篇、T006–T015）。
2. Codex 在独立 worktree 按任务单实现。
3. Sonnet 写任务单、ADR、进度文档。
4. 主会话按波次合入，CI 全绿才算完成。

## 差距分析摘要
- 抠图换底缺失，美颜缺失；图片内容安全检测缺失。
- 续费未产生，加购时主权益过期未处理。
- 后台不能编辑 provider_specs / route_rules，无看板、无管理员账号管理。
- 通知只有 fake 订阅消息，无逐级升级。
- OSS 未实现。
- 小程序缺隐私授权弹窗和协议页（审核必需），私域引导只有客服按钮。
- compose 只有 db、api。

## 方案与决定
分工与合并规则见 [ADR 0005](../adr/0005-multi-agent-workflow.md)。任务 T006–T015 见 `docs/tasks/README.md`；T004 补充决定见 `docs/tasks/T004-receipt-providers.md`。

波次：
- Wave 1：T002、T003、T006、T007、T011。
- Wave 2：T008、T009、T010（第一段）、T013。
- Wave 3：T010（第二段）、T012、T014、T015。

## 改动
仅文档：`docs/tasks/`、`docs/adr/0005`、`docs/progress.md`、`docs/integrations/README.md`。

## 验证
全部波次已合入 main，CI 全绿，见“结果”。

## 执行中的流程决定
- Codex 沙箱不能写 git 索引也不能联网，由 Claude 负责提交、跑 ruff 与 CI。
- Agent 的 isolation worktree 会被自动清理，导致 T003/T011 首次运行成果丢失；改为手工创建并锁定 worktree。
- T008 评审退回：去掉自建网关、直接调用微信接口，短信改阿里云。

## 结果
4 个波次、PR #1–#8 全部合入 main，CI 全绿（最终 315 个测试、两个前端构建、Apifox 同步）。
- Wave 1（PR #1–#5）：T002、T003、T006、T007、T011、T010 第一段、T004。
- Wave 2（PR #6）：T005、T008、T009、T013、T016。
- Wave 3（PR #7）：T010 第二段、T012、T014。
- Wave 4（PR #8）：T015、T017、T018。
- T001–T018 均已完成；真实账号联调待用户提供。

流程经验：
- Codex 沙箱不能写 git 索引也不能联网，由 Claude 负责提交与跑 CI。
- Agent 的 isolation worktree 会被自动清理，成果丢失；改为手工创建并锁定 worktree。
- 按 PR 跑 CI，通过后再 rebase 合入 main。
- 共享文件（`core/config.py`、`core/errors.py`、`.env.example`、迁移、`CONTRACTS.md`、`openapi.json`）由主会话统一合并。
- 新增接口要同步后台接口数断言（T018 CI 发现 34→35）。

## 遗留与下一步
- 架构风险：openapi.json 冲突、共享文件线性合入、抠图同步拖慢请求（超时+降级，以后改异步）、真实退款异步、prod 禁止 fake 模式（主会话在 config.py 加启动检查）。
- 需要用户提供的东西见 `docs/progress.md`。
