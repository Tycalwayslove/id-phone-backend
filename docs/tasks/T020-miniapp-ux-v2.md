# T020 小程序界面 v2（先拍好看，再谈付费）

- 状态：已完成（PR #12）
- 依赖：无（只改前端，后端接口不变）
- 设计：**先完整读 `docs/design/miniapp-ux-v2.md`**，本任务就是把它实现出来；与设计文档冲突时以设计文档为准。

## 只允许改的文件
`miniapp/src/`（含新增组件、hooks、utils）。不改后端、不改 `docs/`、不改 `package.json` 依赖。

## 要求
1. `src/app.scss`：按设计文档 3.2–3.4 换成新的颜色、字号、形状变量；旧变量名保留为别名；NutUI 主色跟随 `--c-primary`。新增公共类 `.photo-frame`（证件照比例相框 + 四角裁切角标，用伪元素 `::before/::after` 加两个空 `View` 实现，**不能用 `*` 选择器**，WXSS 不支持）。
2. `src/app.config.ts`：tab 文字“证件照”改为“我的照片”，颜色跟随新色板。
3. 新增工具：
   - `utils/plans.ts`：`describeBenefits(plan): string[]`、`pickRecommendedPlan(plans, supportsReceipt): PlanOut | undefined`、`unlockablePlans(plans)`（规则见设计 4.6）。
   - `utils/format.ts` 增加 `bgColorName(hex)`（设计 4.5）。
   - `hooks/usePurchase.ts`：把 `pages/plans/index.tsx` 里的下单、`requestPayment`、轮询、fake 支付、幂等键逻辑原样抽出来；套餐页改为调用它，行为不变。
4. 新增组件：`SpecPicker`（4.3）、`ShootGuide`（4.4，“下次不再提示”存本地）、`UnlockSheet`（4.6）、`HeroFrame`（首页主视觉相框，剪影用 CSS 画，背景白/蓝/红轮换，4.2/3.5）、`SpecTile`（常用规格格子：名称、毫米尺寸、可办回执标记）。底部弹出用 NutUI 的 `Popup`（项目已依赖 `@nutui/nutui-react-taro`）。
5. 页面：
   - 首页按 4.2 重做；删除“套餐亮点”，首页不出现任何价格。
   - 制作页按 4.5 重做：按住对比原图、底色中文名、美颜“自然…精致”分段、未付费时“保存高清照片”打开 `UnlockSheet`；支付成功后刷新权益、重新生成、自动保存到相册、提示“已保存到相册”。
   - 规格详情页底部改为打开 `ShootGuide`。
   - 我的照片（`pages/photos`）按 4.7；我的（`pages/me`）按 4.8 调整顺序和文案。
   - `PlanCard` 的权益文案改用 `describeBenefits`。
6. 文案严格按设计文档 3.6：不用“·”拼接、不加“→”、按钮写清动作。
7. 其他页面不改结构，只确认在新变量下显示正常（没有引用已删除的类名）。

## 验收
- 无法联网装依赖时说明即可；Claude 合并时跑 `pnpm run typecheck && pnpm run build`，CI 全绿。
- 结束报告列出：改了哪些文件、和设计文档有出入的地方及原因、需要真机确认的点。
