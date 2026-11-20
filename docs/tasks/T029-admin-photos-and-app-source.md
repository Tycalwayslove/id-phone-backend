# T029 后台查看用户照片、用户来源小程序

- 状态：进行中
- 用户原话：“这个每个用户上传的图片能不能在运营后台看到啊？而且我现在测试，按理来说，应该会新增一个用户才对？我们的用户表没有区分是哪个小程序，后续如果换小程序也不知道是哪个小程序带来的客户。这些细节给补充下”
- 现状（Opus 已查）：
  - 真机登录**确实新建了用户**（开发库 user 4，11-20 01:57），但后台看不出是谁、从哪来。登录是 `WECHAT_MODE=fake`，身份里的 app_id 是占位值 `wx-dev-app`（配置 `WX_MINI_APP_ID` 未改成真实 AppID `wxd518e14f9fdceacc`）。
  - `user_identities` 已有 `provider`、`app_id`、`open_id`；`users` 已有 `first_channel_id`（`channels` 表：推广渠道）。缺的是“应用”这一层：哪个小程序/公众号/以后的支付宝、抖音小程序，及其名称；后台也没展示。
  - 后台没有任何查看用户照片的入口。

## 只允许改的文件
`backend/app/models/`（新表、新列）与**一个**新迁移（授权）、`backend/app/modules/admin/`、`backend/app/modules/auth/`（登录时记录来源应用）、`backend/app/modules/photos/`（只加给 admin 用的跨模块查询函数，写进 `CONTRACTS.md`）、`backend/app/core/deps.py`（新权限点）、`backend/scripts/`（数据回填脚本）、`backend/tests/`、`admin-web/src/`、`docs/api/openapi.json`（生成）、`backend/app/modules/CONTRACTS.md`。

## 要求
### 来源应用
1. 新表 `client_apps`：`id`、`platform`（`check_in`：`wx_mini` 微信小程序、`wx_mp` 微信公众号、`alipay_mini` 支付宝小程序、`douyin_mini` 抖音小程序、`web` 网页）、`app_id`（与 platform 组合唯一）、`name`（运营起的名字）、`status`（`active`/`disabled`）、时间戳。
2. `users.source_app_id`（FK → `client_apps`，`ondelete=SET NULL`，建索引，可空）：用户**首次注册**时的应用，之后不变。
3. 登录（auth 模块）：按身份的 platform + app_id 找 `client_apps`，没有就自动建一条（`name` 先用 app_id），新用户写 `source_app_id`。已有用户不改。
4. 回填脚本 `scripts/backfill_user_source_app.py`：用每个用户最早的身份推断来源应用；默认只打印计划，`--apply` 才写（数据修复用单独脚本，按 CLAUDE.md）。
5. 后台接口：用户列表和详情返回来源应用（名称、平台、AppID）和首次渠道（名称）；用户列表可按 `source_app_id` 筛选；新增 `GET /admin/client-apps`（列表，带各应用用户数）与 `PATCH /admin/client-apps/{id}`（改名称、状态）。权限点：查看 `user:read`，修改 `app:write`（新增，只给 owner）。

### 后台查看照片
6. 新权限点 `photo:read`（owner、operator）。
7. `GET /admin/photos`：游标分页（用 `core/pagination`），筛选 `user_id`、`status`、`matting_level`、`quality_level`；每项含照片 ID、用户 ID、来源、状态、抠图精度、拍后检测结果、保管到期、创建时间、**缩略图地址**（签名 URL，有效期 10 分钟；没有缩略图就用原图签名地址，前端限制显示尺寸）。
8. `GET /admin/photos/{photo_id}`：详情含原图、当前抠图底片、所有导出图（规格名、底色、美颜档位、是否水印、生成时间）的签名地址，以及拍后检测明细。**每次查看详情写一条审计日志** `photo.view`（照片属于敏感个人信息）。列表不写审计。
9. `GET /admin/users/{user_id}` 详情里加最近 12 张照片的摘要（同第 7 条字段），并给出“查看全部”所需的 `user_id`。
10. 接口文档按 CLAUDE.md 写全（中文说明、枚举逐个解释、errors_doc），后台接口数断言随之调整。

### 运营后台前端
11. 用户列表加“来源应用”列与筛选；用户详情加来源应用、首次渠道、“照片”区（缩略图网格，点开大图看原图/抠图/导出，可切换）。
12. 新增菜单“照片”（全部照片，按用户 ID、状态、抠图精度、检测结果筛选，网格展示）和“应用”（列表、改名、停用；需 `app:write`）。
13. 大图查看用 antd `Image` 预览；签名地址过期后重新拉详情。

## 测试
来源应用：新用户写入且不随后续登录改变、自动建应用、回填脚本计划正确；照片：权限点（finance 无权）、分页筛选、详情写审计、签名地址有效期；后台用户详情含照片摘要。

## 协作约束（重要）
只改工作区文件，**不要 git commit、不要 bundle、不要输出 base64**；没有网络。改完跑 ruff、能跑的测试、admin-web 的 `gen:api` 和 typecheck。最后简短报告（标出共享文件和迁移）。
