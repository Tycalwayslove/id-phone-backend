# T023 先拍好看，再选证件

- 状态：进行中
- 依赖：T020、T021、T022 已合入
- 设计：`docs/design/miniapp-ux-v2.md` 第 7 节（先读完整第 7 节，与旧章节冲突时以第 7 节为准）

## 只允许改的文件
`miniapp/src/`；`backend/app/modules/specs/`、`backend/app/core/config.py`、`.env.example`（本任务授权改，报告里列出）、`backend/scripts/seed_dev.py`、新增 `backend/scripts/fix_spec_bg_colors.py`、`backend/tests/specs/`、`docs/api/openapi.json`（用 `scripts/export_openapi.py` 生成）。

## 要求
### 后端
1. 配置 `PREVIEW_SPEC_CODE: str = ""`（写进 `.env.example`，中文注释：还没选证件时用来预览的规格编码）。
2. 新接口 `GET /specs/preview`（不需要登录，operation_id `specs_preview`）：返回 `SpecDetail`。取值顺序：配置的编码且已上架 → 已上架、分类 normal、名称为“一寸”的规格 → 已上架、分类 normal 里排序最靠前的 → 都没有返回 `SPEC_NOT_FOUND`。文档写全。注意路由顺序，别被 `/specs/{code}` 抢先匹配。
3. `scripts/fix_spec_bg_colors.py`：把 `specs.bg_colors` 里的颜色英文名（white/blue/red 等，与 `integrations/receipt_providers/_catalog.py` 的 `_COLORS` 对照）改成十六进制；默认只打印计划，`--apply` 才写；只允许对 `_dev` 结尾的库执行（照 `seed_dev.py` 的保护）。`seed_dev.py` 改为直接写十六进制。
4. 测试：`/specs/preview` 的三级回退和 404；修复脚本的转换函数（纯函数单测即可）。

### 小程序
5. 首页“开始拍”：打开拍摄提示（`ShootGuide`）→ 拍照/相册 → 进入制作页且**不带** `spec_code`。不再弹城市面板和选规格面板。首页规格格子和规格详情页的入口保持原样（带规格，直接进第 2 步）。`ShootGuide` 在没有规格时，第 3 条提示写“不用找白墙，背景之后可以随便换”。
6. 制作页按设计 7.2 分两步：
   - 没有 `spec_code` 时调 `GET /specs/preview` 作为预览规格，处于第 1 步；
   - 第 1 步主按钮“选证件类型”→ 复用 T022 的城市面板（未选过城市时先弹，可跳过）和选规格面板；选中后用 `Taro.redirectTo`/页面内状态切到第 2 步（推荐页面内状态，避免重新上传），不重新拍照；
   - 第 2 步证件信息行“换一个”同样打开选规格面板；
   - 换证件时的底色、美颜自动调整和提示文案按 7.2；
   - 第 1 步不显示价格、不显示“保存高清照片”和“办理回执”。
7. `utils/format.ts` 的 `bgColorName` 兼容英文名（white/blue/red/…），色块渲染时英文名先转成十六进制。

## 协作约束（重要）
只改工作区文件，**不要 git commit、不要 bundle、不要输出 base64**。改完跑 `ruff check`、`ruff format`；最后简短报告：改了哪些文件、与设计的出入、需要真机确认的点。
