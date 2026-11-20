# 0025 照片链路接入抠图与内容安全（T012）

- 日期：2026-11-19
- 状态：已完成（真实抠图服务与内容安全回调待配置）
- 相关提交：127a751、c963d78；PR #7

## 需求
任务单 T012：`create_photo` 调抠图；上传后调用微信 `mediaCheckAsync`，结果异步回写，未通过的照片不能导出、下载；非 fake 模式不再抛 `NotImplementedError`。

## 拆解
1. 创建照片时生成 RGBA 抠图，失败或超时降级原图。
2. 原图上传后提交微信内容安全检测，回调验签后按 `trace_id` 回写。
3. 导出、下载按检测结果拦截。

## 方案与决定
- 导出优先用抠图；抠图失败或超时降级为原图并记日志（不含图片内容）。
- 检测未出结果或检测失败返回 `PHOTO_NOT_READY`；有风险或需复核返回 `PHOTO_REJECTED`（403）。
- 新增微信消息推送回调 `GET/POST /wechat/media-check`（验签），配置 `WX_MSG_TOKEN`。
- 主会话合入时：`CurrentUser` 新增 `wx_mini_open_id`，按会话 `identity_id` 取小程序 openid（核对用户、provider=wx_mini、当前 AppID）；回执提交/重提接口声明 `PHOTO_REJECTED`；更新 `docs/api/openapi.json`（61 个路径）。
- 无需迁移。

## 改动
- `backend/app/modules/photos/{repo,router,schemas,service}.py`、`backend/app/integrations/wechat.py`（新增内容检测）。
- `backend/app/core/{config,errors}.py`、`backend/.env.example`；`backend/app/core/deps.py`、`receipts/router.py`（c963d78）。
- 测试：`backend/tests/photos/test_media_check.py`、`test_photos.py`。

## 验证
- PR #7 CI 全绿；抠图成功、失败降级、检测通过、检测不通过禁止导出均有测试。

## 遗留与下一步
- `RealMatting` 仍是占位（真实抠图服务待选型），当前降级为原图。
- 内容安全回调需公网 HTTPS 与 `WX_MSG_TOKEN`（微信公众平台消息推送配置）。
- 真实微信模式下旧照片无检测记录，需重新上传。
- 小程序对 `PHOTO_NOT_READY`/`PHOTO_REJECTED` 的提示见 T017。
