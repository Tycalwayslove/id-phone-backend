# T028 精细抠图（BiRefNet 后台替换）、底部渐隐修正、检测明细

- 状态：已完成，待 PostgreSQL 和小程序真机验证
- 实现与验证：[开发日志 0036](../devlog/0036-fine-matting.md)
- 依赖：T024（同一分支 `codex/t024`，未合入）
- 背景（Opus 用 4 张真实自拍评估，2026-11-20）：
  - MODNet 在百叶窗、出风口等复杂背景下把背景当头发；BiRefNet（MIT）同样 4 张头部轮廓干净，但 CPU 每张 5~8 秒（1024×1024 输入，ImageNet 归一化，输出取最后一个、经 sigmoid）。
  - 近距离自拍裁剪后，T024 的“底部渐隐延伸”是复制末行像素，出现竖条纹，比硬边还难看。
  - 鹧应 `/idphoto/check` 按 item_id 713 只查 19 项（不含背景纯净度、头部比例、耳朵、眉毛），评估脚本没保存明细，看不出查了什么。

## 只允许改的文件
`backend/app/modules/photos/`、`backend/app/integrations/matting.py`、`backend/app/workers/`、`backend/app/models/photo.py` 与一个新迁移（如需要，授权）、`backend/app/core/config.py`、`backend/.env.example`、`backend/tests/`、`backend/scripts/eval_pipeline.py`、`miniapp/src/pages/editor/`、`miniapp/src/api/photos.ts`、`docs/api/openapi.json`（生成）。

## 要求
1. **两段式抠图**：上传时照旧用 MODNet（快，用户马上能修图）；之后在后台用 BiRefNet 重新抠图，完成后替换照片的抠图底片。
   - 后台执行：照片创建成功并提交后，放进进程内的有界线程池执行（并发上限可配置，默认 1，`FINE_MATTING_WORKERS`）；worker 每轮补做“快速抠图已超过 2 分钟仍未精细抠图”的照片（防进程重启丢任务）。不阻塞请求。
   - 照片增加抠图精度状态（如 `matting_level`: `fast` / `fine` / `failed`），`PhotoOut` 返回，枚举写全 description。
   - 导出缓存必须区分抠图底片（缓存键包含当前抠图文件，或换底片时让旧导出失效），精细抠图完成后再导出要用新底片。
   - `MATTING_MODE=local` 下才启用精细抠图；模型缺失时记日志并标记 `failed`，不影响快速抠图结果。
2. **小程序制作页**：照片 `matting_level` 为 `fast` 时，每 3 秒轮询照片（最多 60 秒），变成 `fine` 后自动重新生成预览；期间在预览下方显示一行小字“正在精细抠图，边缘会更干净”，不打断操作。
3. **底部处理**：去掉“复制末行像素”的延伸。改为：原图下沿以下用底色填充，同时把人像最后约 4% 成品高度做 alpha 线性渐隐到底色，过渡自然、无条纹。仍然先按 T024 的规则尽量选不越界的头部占比。
4. **评估脚本**：保存每次检测的完整 `passed_list` 到报告（每项 key、是否通过、msg、实测值和单位），并在报告顶部列出“本次检测覆盖的检查项”。支持 `--matting fast|fine|both` 对比两种抠图。
5. 测试：两段式抠图状态流转、导出缓存随底片失效、渐隐无条纹（合成图：渐隐区每列像素单调、相邻列差异小）、评估脚本报告包含明细（用模拟响应）。

## 协作约束（重要）
只改工作区文件，**不要 git commit、不要 bundle、不要输出 base64**；没有网络，模型已在 `backend/models/`。改完跑 ruff 和能跑的测试；能读到 `/Users/mac/id-phone/backend/eval/input` 就跑一次 `--matting both` 评估（不加 `--check`）。最后简短报告。
