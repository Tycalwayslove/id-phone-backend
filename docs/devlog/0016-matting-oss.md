# 0016 抠图美颜、OSS 与配置项（T006 + T007）

- 日期：2026-11-19
- 状态：已完成
- 相关提交：733e9cf（配置与生产禁止 fake）、ace7bb7（T006）、3ebcc5f（T007）；PR #2

## 需求
T006：补齐照片制作里缺的抠图换底和美颜。T007：实现 `OssStorage`，`STORAGE_MODE=oss` 可用。另需补齐配置项，并避免误把 fake 配置上线。

## 拆解
1. 配置：新增 worker 间隔、抠图超时；生产禁止 fake；`.env.example` 补全。
2. T006：抠图适配器（含 fake）与 imaging 美颜。
3. T007：OSS 签名与 put/get/delete/url。

## 方案与决定
- `APP_ENV=prod` 时 WECHAT/PAY/RECEIPT 为 fake 或 SECRET_KEY 为默认值则启动失败；演示环境可显式设 `ALLOW_FAKE_IN_PROD=true`。
- `integrations/matting.py`：`MattingClient` 接口（原图转 RGBA PNG）、`FakeMatting`（按左上角背景色抠除纯色背景）、`RealMatting` 骨架（超时转 `TimeoutError`），按 `MATTING_MODE` 选择。
- imaging：RGBA 先按 `beauty_level` 1–5 轻度平滑提亮再合成底色；`beauty_level=0` 输出与改动前逐字节一致。接入 photos/service 由 T012 负责。
- OSS：httpx 自实现 V4 签名（OSS4-HMAC-SHA256），不引 SDK；私有对象，下载用带过期时间的签名 URL；get 404 抛 `FileNotFoundError`，delete 幂等，超时转 `TimeoutError`，AccessKey 不进日志和异常。新增配置 `OSS_REGION`（留空时从标准 Endpoint 推出）。

## 改动
- 配置：`backend/app/core/config.py`、`backend/.env.example`。
- T006：新增 `backend/app/integrations/matting.py`，改 `backend/app/modules/photos/imaging.py`，测试 `tests/integrations/test_matting.py`、`tests/photos/test_imaging.py`。
- T007：`backend/app/integrations/storage.py`，测试 `tests/integrations/test_storage.py`。

## 验证
- 抠图换底取样像素、beauty=0 不变、超时、OSS 签名头与 404、超时均有单测。
- ruff 与 CI 由 Claude 执行；PR #2 合入 main，CI 全绿。

## 遗留与下一步
- 抠图真实服务商未选定，`RealMatting` 仅为骨架。
- 抠图与内容安全接入照片链路见 T012。
- 需要用户提供阿里云 OSS 账号（见 `docs/progress.md`）。
