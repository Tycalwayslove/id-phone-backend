# T007 阿里云 OSS 存储

- 状态：进行中（Codex）
- 依赖：无（Wave 1）

## 目标
实现 `integrations/storage.py` 里的 `OssStorage`（现为未实现），`STORAGE_MODE=oss` 时可用。

## 只允许改的文件
`backend/app/integrations/storage.py`、`backend/tests/integrations/test_storage.py`。

新增配置项（`OSS_ENDPOINT`、`OSS_BUCKET`、`OSS_ACCESS_KEY_ID` 等）写进报告，由主会话改 `config.py` 与 `.env.example`。

## 要求
1. 实现 `put / get / delete / url`；`url` 返回带有效期的签名链接。
2. 不引入 OSS SDK，用 `httpx` 自己实现签名（V4 或 V1，选其一并写在注释里）。
3. 密钥只从配置读，不进日志；错误不回显签名串。
4. 与 `LocalStorage` 接口一致，业务代码不改。

## 验收
- 用 `httpx.MockTransport` 测签名头与四个方法（含 404、超时）。
- `ruff`、`pytest` 通过，CI 全绿。
