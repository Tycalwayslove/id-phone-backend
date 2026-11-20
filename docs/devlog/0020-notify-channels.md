# 0020 真实通知通道与逐级升级（T008）

- 日期：2026-11-19
- 状态：已完成（真实通道联调待账号）
- 相关提交：14655ec；PR #6

## 需求
任务单 T008：让通知真正发出去，小程序订阅消息、公众号模板消息、企业微信、短信，按档位逐级升级。

## 拆解
1. 小程序订阅消息发送（`wechat.py`）。
2. `notify_channels.py`：公众号、企业微信、短信，统一接口，均带 fake。
3. `send_due` 真实发送与逐级升级，重试有上限。
4. 日志脱敏。

## 方案与决定
- 评审退回重做：首版引入了自建网关。去掉，改为小程序订阅消息直连微信，复用小程序 access_token。
- 公众号使用独立凭据（`WX_MP_APP_ID`、`WX_MP_APP_SECRET`），令牌缓存。
- 企业微信主动发消息需员工确认：保留接口，real 模式跳过并升级到下一级，不报错。
- 短信改用阿里云，自实现 ACS3 签名。
- 升级按 channel：`mini_subscribe → mp_template → wecom → sms`；`step` 仍表示档位。
- 逐条提交；退避重试，上限后标记失败；日志去除 access_token 等敏感查询串。
- 无需迁移。

## 改动
- `backend/app/integrations/wechat.py`、`notify_channels.py`（新）。
- `backend/app/modules/notify/{repo,service}.py`、`users/{repo,service}.py`（读取通知所需用户信息）。
- 配置：`NOTIFY_CHANNELS`、`MINI_SUBSCRIBE_MODE`、`MP_TEMPLATE_MODE`、`WECOM_MODE`、`SMS_MODE`、`WX_MP_*`、`MINI_SUBSCRIBE_TEMPLATES`、`MP_TEMPLATE_TEMPLATES`、`SMS_ACCESS_KEY_ID`、`SMS_ACCESS_KEY_SECRET`、`SMS_SIGN_NAME`、`SMS_TEMPLATES`；`CONTRACTS.md` 同步。
- 测试：`backend/tests/notify/test_channels.py`、`test_delivery.py`。

## 验证
- PR #6 CI 全绿（273 个测试）；覆盖各通道 fake 与 `MockTransport`、升级顺序、重试上限、不重复发送。

## 遗留与下一步
- 需要用户提供：`WX_MP_APP_SECRET` 与公众号模板、小程序订阅消息模板 ID、阿里云短信账号/签名/模板；企业微信员工确认流程待设计。
- T012 依赖本任务。
