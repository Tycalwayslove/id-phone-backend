# T024 自建照片处理流水线（抠图、人脸定位裁剪、精修、拍后检测、过检评估）

- 状态：已完成，待 PostgreSQL 和授权照片验证
- 实现与验证：[开发日志 0035](../devlog/0035-in-house-photo-pipeline.md)
- 决策：先读 `docs/adr/0007-in-house-photo-pipeline.md`；拍后检测的用户侧要求见 `docs/design/shoot-flow.md` 第 4 节。
- 已由 Claude 准备好：依赖 `onnxruntime`、`opencv-python-headless`、`numpy`（已加进 pyproject/uv.lock）；模型在 `backend/models/`（`scripts/download_models.py`，不进 Git），本机 CPU 实测 MODNet 512px 约 0.22 秒、YuNet 可加载。

## 只允许改的文件
`backend/app/integrations/matting.py`、`backend/app/modules/photos/`（含新增子模块，建议 `photos/pipeline/` 下按 `matting.py`、`face.py`、`crop.py`、`retouch.py`、`quality.py` 分文件）、`backend/app/models/photo.py` 与**一个**新 Alembic 迁移（授权，报告里说明）、`backend/app/core/config.py`、`backend/.env.example`、`backend/tests/photos/`、新增 `backend/scripts/eval_pipeline.py`、`docs/api/openapi.json`（`scripts/export_openapi.py` 生成）、`.gitignore`。不改 `miniapp/`。

## 要求
1. **抠图**：`MATTING_MODE` 增加 `local`（开发与生产推荐值，写进 `.env.example`）。`LocalMatting` 用 onnxruntime 跑 MODNet：输入短边缩放到 512 并对齐到 32 的倍数、归一化到 [-1,1]，输出 alpha 放大回原尺寸，返回 RGBA PNG（与现有 `MattingClient` 协议一致）。会话进程内单例、懒加载；模型文件缺失时给出明确报错（提示运行下载脚本）。`fake` 模式保留给测试。
2. **人脸**（`face.py`）：YuNet 检测，返回人脸框、5 个关键点、置信度；按置信度阈值过滤；输入过大时先缩小再检测、结果换算回原图坐标。
3. **人脸定位裁剪**（`crop.py`）：替代 `imaging._center_crop`。用人脸框和抠图 alpha 找头顶（人脸框上方 alpha>0.5 的最高行）、下巴（人脸框下沿，可按关键点微调）。目标：头部高度（头顶到下巴）占成品高度约 0.62（允许 0.55~0.70），头顶留白约成品高度 0.08，左右以两眼中点居中。取景超出原图时用底色补齐，不拉伸。检测不到人脸时退回居中裁剪。这些比例放成常量并注释来源（通用证件照要求），以后可按规格配置。
4. **精修**（`retouch.py`），全部不改变几何：
   - 自动光影（始终开启，在铺底色之前作用于人像）：灰世界白平衡的温和版、曝光校正到合理亮度、以人脸中线为界的左右亮度差校正（阴阳脸，最多修正一半差值）。
   - 美颜 `beauty_level`（0..`beauty_max`）：皮肤区域 = 人脸框扩展椭圆 ∩ YCrCb 肤色范围，减去以眼睛、嘴角关键点为中心的保护区；在皮肤区域内做保边平滑（用 box filter 自行实现导向滤波，不依赖 opencv-contrib），按档位线性加强；LAB 空间按档位轻微降低 b（去暗黄）、轻微提亮 L；蒙版边缘羽化。
   - 祛痘：`render` 接口新增可选参数 `blemishes: list[{x, y}]`（0..1 归一化坐标，基于成品图，最多 10 个），对每点半径约人脸宽 1.5% 的小圆 `cv2.inpaint`。写进请求模型并文档写全。
   - 去掉旧的整图模糊美颜。
5. **拍后快速检测**（`quality.py`）：照片创建完成时计算，存进 `photos.quality`（JSONB，可空；新迁移）。`PhotoOut`/`PhotoDetail` 增加 `quality: {level: "ok"|"warn"|"fail", issues: [{code, message}]}`，枚举逐个写 description。至少：`no_face`（fail）、`multiple_faces`（fail）、`face_too_small`、`face_off_center`、`too_dark`、`too_bright`、`not_frontal`（用两眼与鼻尖关键点的对称性估计偏头）、`uneven_light`（左右脸亮度差）。`message` 是给用户看的中文，说清怎么改（如“脸有点小，请靠近一点再拍”）。
6. **过检评估脚本** `scripts/eval_pipeline.py`（离线工具，不进业务代码路径）：
   - 输入 `--input <目录>`（开发者自己的测试照片，默认 `backend/eval/input/`，整个 `backend/eval/` 加进 `.gitignore`），`--spec <规格编码>`（可多个），`--beauty 0,2,4`。
   - 对每张图跑完整流水线，输出原图、抠图、各档位成品到 `backend/eval/output/<时间戳>/`，并生成一页 `report.html`（并排对比 + 检测结果）。
   - `--check` 时调用服务商 `POST /idphoto/check`（鹧应，`ZHEYING_APP_KEY`，表单字段 `key`、`image`=base64、`item_id` 来自该规格的服务商映射，详见下方“检测接口要点”）；运行前打印“将调用 N 次，预计 N×0.012 元”，需加 `--yes` 才真正调用。结果写进报告：是否通过、未通过项的 `key` 与 `msg`。
   - 只读数据库（取规格和映射），不写库。
7. 测试：裁剪比例（合成图：画一个椭圆“脸”+ 伪造检测结果，断言头部占比和留白）、精修不改变几何（对关键点附近做差异检测：几何保护区像素位移为 0 的思路——至少断言保护区内像素差很小）、快速检测各 issue、`blemishes` 参数校验、模型缺失时报错清楚。测试不依赖真实人脸照片；需要模型的测试在模型文件不存在时 `skip`。

## 检测接口要点（来自鹧应文档，Claude 已核实）
- `POST https://api.zjzapi.com/idphoto/check`，`application/x-www-form-urlencoded`，返回 `{code, msg, data}`，`code=0` 才成功。
- 参数：`key`、`image`（base64）、`item_id`（可选，传了按该规格检测）。也可不传 `item_id` 改传 `width_px`、`height_px`、`dpi`、`bg_colors` 等，脚本里用 `item_id`。
- 返回 `data.passed_status`（1 通过 0 不通过）、`data.passed_list`（每项 `key`、`passed`、`msg`、`detail`）。
- 计费：检测成功扣 0.012 元。

## 协作约束（重要）
沙箱写不了 Git 索引：**只改工作区文件，不要 git commit、不要 bundle、不要输出 base64**。没有网络：不要尝试下载模型或调用服务商；模型已在 `backend/models/`。改完跑 `ruff check`、`ruff format`；能跑的测试就跑。最后简短报告：改了哪些文件（标出共享文件和迁移）、与任务单的出入、建议的默认参数及理由。
