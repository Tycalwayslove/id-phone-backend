# T008 真实通知通道与逐级升级

- 状态：已完成（PR #6，提交 14655ec；评审退回重做：去掉自建网关，小程序订阅消息直连微信，短信改阿里云，企业微信 real 跳过并升级；记录见 devlog 0020）
- 依赖：T002（notify 新增了 `create_task_once`）；Wave 2

## 目标
让通知真正发出去：小程序订阅消息发送，加上公众号模板消息、企业微信、短信，按步骤逐级升级。

## 只允许改的文件
`backend/app/integrations/wechat.py`、`backend/app/integrations/notify_channels.py`（新）、`backend/app/modules/notify/`、`backend/tests/notify/`。

配置项与错误码写进报告，由主会话合入。

## 要求
1. `wechat.py` 新增订阅消息发送（subscribeMessage.send）。
2. `notify_channels.py`：公众号模板、企业微信、短信三个通道，统一接口，均带 fake 实现。
3. `send_due` 真实发送：step 2→3→4 逐级升级（上一级失败或用户未读才升级），每条任务单条提交，失败重试有上限，超限标记失败。
4. 日志不打印手机号、openid、令牌、密钥。

## 验收
- 各通道 fake 与 `MockTransport` 单测；升级顺序、重试上限、不重复发送有测试。
- `ruff`、`pytest` 通过，CI 全绿。
