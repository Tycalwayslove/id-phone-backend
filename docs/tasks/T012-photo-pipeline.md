# T012 照片链路接线

- 状态：进行中（Codex，Wave 3）
- 依赖：T003、T006、T008；Wave 2 末 / Wave 3

## 目标
把抠图和图片内容安全检测接进照片流程。

## 只允许改的文件
`backend/app/modules/photos/service.py`、`backend/app/modules/photos/repo.py`、`backend/app/integrations/wechat.py`（只新增内容检测）、`backend/tests/photos/`。

需要新增表或字段，把迁移方案写进报告，由主会话合入。

## 要求
1. `create_photo` 调抠图生成 matting 文件；失败或超时降级为原图并记日志（不含图片内容）。
2. 上传后调用微信 `mediaCheckAsync`，检测结果异步回写；未通过的照片不能导出、下载。
3. 非 fake 模式不再抛 `NotImplementedError`。

## 验收
- 抠图成功、失败降级、检测通过、检测不通过禁止导出均有测试。
- CI 全绿。
