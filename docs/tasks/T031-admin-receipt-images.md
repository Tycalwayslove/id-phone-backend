# T031 后台回执详情展示照片与回执图

- 状态：已完成
- 用户原话：“我看了下回执页面已经有一个回执 R20261118000001 了，但是对应的回执照片信息，并没有在运营后台展示，帮我展示一下。”
- 现状（Opus 已查）：该回执是 seed 演示数据（user 1、photo 2、`receipt_file_id`=9、`image_code`=DEMO-IMG-0001；attempt 1 被驳回用 render 2，attempt 2 成功用 render 3）。`AdminApplicationDetail` 与 `AdminAttemptOut` 没有任何图片字段；后台回执详情只有文字。另外 seed 只建了文件记录、没写真实文件，`/files/dev/u1/p2/original_f3.jpg` 返回 404。

## 只允许改的文件
`backend/app/modules/admin/`、`backend/app/modules/receipts/`（只加给后台用的查询，写进 `CONTRACTS.md`）、`backend/app/modules/photos/`（如需复用 T029 的后台照片摘要/签名地址函数，只调 service）、`backend/app/modules/CONTRACTS.md`、`backend/scripts/seed_dev.py`、`backend/tests/`、`admin-web/src/`、`docs/api/openapi.json`（生成）。

## 要求
1. `GET /admin/receipt-applications/{app_no}` 详情增加（签名地址有效期 10 分钟，复用 T029 照片接口的签名方式）：
   - `photo`：用户的照片摘要（照片 ID、原图缩略图地址、拍后检测结果），可点进后台照片详情；
   - `receipt_image_url`：官方回执图（`receipt_file_id`），没有为空；
   - 每条 `attempts[]` 增加 `render`：这次提交的证件照（规格名、底色、美颜档位、是否水印、图片地址）。
   - 文件已清理（purged）或不存在时对应地址为空，并给出 `missing_reason`（如“文件已清理”），不报错。
   - 查看回执详情要写一条审计 `application.view`（含个人照片和回执，属于敏感信息）；权限点沿用 `application:read`，另外图片字段要求同时有 `photo:read`，没有时图片字段为空（文字信息照常返回）。
2. 后台回执详情页：顶部并排展示“用户照片”“最终提交的证件照”“官方回执图”三张（antd `Image` 可放大），图像号旁可复制；提交记录表每行加证件照缩略图（点开大图，驳回的那次能对照驳回原因）。图片缺失时显示占位和原因。
3. `seed_dev.py`：为演示数据生成并写入真实的占位图片文件（用 Pillow 画剪影示意图和“演示回执”字样图，**不用真人照片**），使开发库演示数据的图片都能打开；已存在的文件不覆盖。
4. 测试：详情含三类图片地址；无 `photo:read` 时图片为空；文件缺失时 `missing_reason`；审计写入。

## 协作约束（重要）
只改工作区文件，**不要 git commit、不要 bundle、不要输出 base64**；没有网络。改完跑 ruff、能跑的测试、admin-web 的 `gen:api`、typecheck、build。最后简短报告。
