# T006 抠图适配器与美颜

- 状态：进行中（Codex）
- 依赖：无（Wave 1）

## 目标
补齐照片制作里缺的抠图换底和美颜：新增抠图适配器（带 fake），`make_render` 把透明图合成到底色，`beauty_level` 用 Pillow 轻度磨皮。

## 只允许改的文件
`backend/app/integrations/matting.py`（新）、`backend/app/modules/photos/imaging.py`、`backend/tests/integrations/test_matting.py`、`backend/tests/photos/test_imaging.py`。

新增配置项、错误码、迁移不直接改共享文件，写进任务报告，由主会话合入。

## 要求
1. `MattingClient` 接口：输入原图字节，输出带透明通道的 PNG 字节；`fake` 实现（如按简单规则生成透明背景）；`get_matting_client()` 按配置返回。
2. `make_render` 接收透明图，按规格底色合成，尺寸与现有输出一致。
3. `beauty_level` 0~N：0 时输出与现有结果逐字节一致；>0 用 Pillow 轻度磨皮，不引入重依赖。
4. 网络超时抛 `TimeoutError`，由调用方（T012）降级。
5. 密钥只从配置读，不进日志。

## 验收
- 透明图换底颜色正确（取样像素断言）。
- `beauty=0` 输出不变。
- 超时抛 `TimeoutError`。
- `ruff check`、`ruff format`、`pytest` 通过，CI 全绿。
