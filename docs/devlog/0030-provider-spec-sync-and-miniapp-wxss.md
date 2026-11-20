# 0030 服务商规格目录同步（T019）与小程序 WXSS 编译修复

- 日期：2026-11-19
- 状态：已完成（真实目录待密钥）
- 相关提交：b09b7a8（PR #10）、4c2fa23（PR #9）

## 需求
用户原话：“服务商的规格是不是没有将各大服务商的规格全部拉下来啊？然后小程序端也打不开，编译错误。”

## 拆解
1. 服务商规格目录同步（T019）：适配器能读服务商的完整规格目录，并同步到本地 `specs` 与服务商映射。
2. 小程序在微信开发者工具里编译失败，定位并修复。

## 方案与决定
**规格目录同步（T019，PR #10）**
- 适配器新增 `list_items` / `get_item`，读取服务商 `/item/list`、`/item/get`（免费接口，需要 `ZHEYING_APP_KEY` / `QIANWEIYUN_APP_KEY`）；fake 模式内置一份样例目录。
- `sync_provider_specs` 规则：
  - 已有规格只更新照片参数（尺寸、dpi、背景色、文件大小），运营配置不动；
  - 目录里的新规格：新建为未上架，映射禁用，成本 0，等运营确认后再启用；
  - 目录里已不存在的条目：其映射被禁用。
- 后台接口 `POST /api/v1/admin/providers/{code}/sync-specs`（权限 `provider:write`，写审计日志），后台服务商页新增“同步规格”按钮。
- 黔微云适配器正名：`clipimg` 改为 `qianweiyun`，配置 `CLIPIMG_*` 改为 `QIANWEIYUN_*`（接口地址 `https://api.qwyun.top`）；seed 中的适配器名从错误的 “ZheyingAdapter” / “ClipimgAdapter” 修正。细节见 `docs/tasks/T019*.md` 与 `docs/integrations/zheying.md` 第 16 节。

**小程序 WXSS 编译错误（PR #9）**
- 报错：`wxss 编译错误 ./app-origin.wxss(7:1214): error at token '*'`。原因是 WXSS 不支持 `*` 通配选择器。
- 修复：`src/app.scss`（`.list-gap`、`.bottom-bar`）和 `PrivacyPopup/index.scss` 里的 `*` 改为 flex `gap` 加显式的 `> view, > button` 选择器。

## 改动
- 后端：适配器（zheying、qianweiyun）、`sync_provider_specs`、后台接口与 schemas、配置项 `QIANWEIYUN_*`、seed、`.env.example`、`docs/api/openapi.json`。
- admin-web：服务商页“同步规格”按钮。
- 小程序：`src/app.scss`、`PrivacyPopup/index.scss`。

## 验证
- 两个 PR 的 CI 均全绿。
- 本地开发库：服务商适配器名已修正，fake 模式跑同步：鹧应新建 6 / 更新 8；黔微云新建 6 / 未变 8。
- 小程序：用开发者工具 CLI 自动模式加 miniprogram-automator，首页、规格、照片、我的、套餐、订单、回执页均能渲染并显示后端数据。
- 仍有一条无害警告 “Template tmpl_0_div not found”，不影响使用。

## 遗留与下一步
- 真实规格目录需要用户提供 `ZHEYING_APP_KEY` / `QIANWEIYUN_APP_KEY`，目前只在 fake 样例上验证。
- 已部署环境需把 `CLIPIMG_APP_KEY` 改名为 `QIANWEIYUN_APP_KEY`，并修正 `providers.adapter` 的值。
- 可立图目前没有真实适配器。
