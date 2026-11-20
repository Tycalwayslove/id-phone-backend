# T021 规格目录聚合、同步修复、按城市选规格（后端 + 后台）

- 状态：进行中
- 依赖：无。与 T020（只改 miniapp）并行，本任务**不改 `miniapp/`**。
- 决策：先读 `docs/adr/0006-aggregated-spec-catalog.md`。

## 背景：同步报错的根因（已由 Opus 用真实接口确认）
- `/item/list` 两家各 774 条，全部能被 `parse_item` 解析，编号和内容一致（同一上游）。
- 同步对每条缺文件大小的条目调用 `/item/get`，而真实返回与代码假设不同：
  - 鹧应：`data` 直接是条目，编号字段是 `item_id`（不是 `id`）；
  - 黔微云：`data` 是 `{"item": {...}}`，里面编号字段也是 `item_id`；
  - 详情里也没有文件大小（鹧应只有 `file_size_msg` 文字，黔微云为 null）。
  所以第一条详情就抛 `回执服务商规格数据无效`，整次同步 503。
- 鹧应列表还带 `is_receipt`（"1"=可办回执）、`receipt_param`（JSON 字符串，如 `["text_mobile","text_city","text_name","text_idcard"]`）、`category`（"0" 职业形象照、"1" 常用尺寸、"2" 签证护照、"3" 其他/证件/报名）。黔微云列表有 `file_size_min/max`、`price`，没有 `is_receipt`。
- 未知底色：`sky_blue`、`gray`、`dark_red`，以及 `pose_*`（姿势照，不是底色）。

## 只允许改的文件
`backend/`（含 `app/core`、迁移——本任务授权你改共享文件，但必须在报告里列出）、`admin-web/src/`、`docs/api/openapi.json`（用 `scripts/export_openapi.py` 生成）。不改 `miniapp/`、不改其他 `docs/`。

## 要求
1. **适配器修复**（`integrations/receipt_providers/`）：
   - `get_item` 兼容真实格式：解包 `{"item": ...}`，编号字段取 `item_id`，没有再取 `id`。
   - `ProviderItem` 增加：`is_receipt: bool | None`、`receipt_fields: list[str]`（解析 `receipt_param`，非法则空）、`provider_category: str | None`。
   - 底色补 `sky_blue`、`gray`、`dark_red`（取合理色值并注释“近似值”）；`pose_*` 静默忽略；未知底色每次同步只汇总记一条日志（数量），不再逐条刷屏。
   - fake 目录样例补上这些字段，测试用。
2. **同步不再逐条调 `/item/get`**：列表已是全量数据，缺文件大小就留空。
3. **跨服务商合并**（ADR 0006 第 2 条），实现在 `modules/specs/service.py` 的同步里：
   - 先按 `(upstream_group, provider_item_id)` 找同上游其他服务商已映射的规格；再按 `(规范化名称, width_px, height_px)` 找；都没有才新建，编码 `cat_<upstream_group 或服务商编码>_<编号>`（冲突加后缀，沿用现有逻辑）。
   - 规范化名称：去掉全半角空格、统一全半角括号。
4. **分类与地区**：
   - `is_receipt` 为真 → `receipt`；否则名称含“考试、报名、网申、学籍、中考、高考、人事”→ `exam`；否则 `normal`。只在**新建**规格时设置，已有规格不改分类。
   - 新增 `app/core/regions.py`（读 `app/data/regions.json`，已提供，见 `app/data/README.md`）：`resolve_region(name) -> str | None`（先匹配市“广州市/广州”，再匹配省“广东省/广东”；最长匹配优先）、`province_of(code)`、`region_name(code)`。新建规格时写入 `region_code`。
5. **回执表单**：新建回执规格时，按 `receipt_fields` 生成 `form_schema` 和该服务商映射的 `param_mapping`：`text_name`→`name` 姓名、`text_idcard`→`idcard` 身份证号、`text_mobile`→`mobile` 手机号、`text_city`→`city` 所在城市；未知字段原样作 key、label 用字段名，并在同步结果里标出。先看 `receipts/service.py` 现有的表单校验和映射用法，保持一致（身份证号的校验、加密存储不能绕过）。
6. **同步后默认可用**（ADR 0006 第 3 条）：同步接口加查询参数 `auto_publish: bool = true`。为真时：**新建**的规格 `active`、新建的映射 `is_enabled=true`、为新映射建一条路由规则（`region_code` 为空，`priority` 默认 100）。**已有**规格、映射、规则的状态和优先级一律不动。同一规格被第二家服务商合并进来时，也给第二家建映射和路由规则（同样受 `auto_publish` 控制）。
7. **用户端接口**：
   - `GET /specs` 增加 `region_code`（6 位，市或省）：返回 `region_code` 为空 + 该省 + 该市的规格；不传保持现状。
   - `SpecOut`、`SpecDetail` 增加 `region_name`（如“广州市”“广东省”，全国通用为空）。
   - 新增 `GET /spec-regions`（不需要登录）：返回有地区专属、已上架规格的省和市（按省分组，含规格数），给小程序做城市选择。operation_id `spec_regions_list`，文档写全。
8. **后台**：`GET /admin/specs` 增加 `region_code` 筛选；规格编辑表单的地区码旁显示识别出的地区名；同步确认弹窗加“同步后自动上架”勾选（默认勾上），传 `auto_publish`。
9. **开发库数据修复脚本** `scripts/merge_catalog_specs.py`：把 T019 期间按服务商重复建的 `zy_*`/`qwy_*` 规格合并（同上游同编号 → 保留一个，映射挪过去，删掉没有被任何照片、导出、回执引用的重复规格）；默认只打印计划，`--apply` 才执行；只允许对名字以 `_dev` 结尾的库执行（参照 `seed_dev.py` 的保护）。
10. 测试：适配器真实格式（两家 `get_item` 样例）、合并（同上游、异上游按名称尺寸）、地区识别（市、省、全国、最长匹配）、`auto_publish` 开关、再次同步不覆盖运营修改、`/specs?region_code=`、`/spec-regions`。后台接口数断言随新增接口调整。

## 验收
- `ruff check`、`ruff format` 通过；能连数据库就跑 pytest（沙箱可能不能，说明即可）。`alembic check` 无差异（如需迁移，按 CLAUDE.md 规则写并在报告说明）。
- 分 3～5 次提交，信息中文；末尾 `Co-Authored-By: Codex <noreply@openai.com>`；不要 push。
- 结束报告：改了哪些共享文件、和 ADR/任务单的出入及原因、需要用户本机做的事（如运行合并脚本）。
