# 0026 运营后台前端：看板、通知、路由、管理员（T010 第二段）

- 日期：2026-11-19
- 状态：已完成
- 相关提交：e81878c；PR #7

## 需求
任务单 T010 第二段（T009 合入后）：新增数据看板、通知任务、路由规则（含 provider_specs）、管理员账号与角色页面；菜单与按钮按 `permissions` 显示。

## 拆解
1. 看板与通知任务页。
2. 服务商规格与路由规则增删改。
3. 管理员管理与临时密码登录。

## 方案与决定
- 数据看板为默认首页；通知任务为列表页。
- 路由配置成本在界面用元，提交时转换为分（`_fen`）。
- 管理员支持新建、停用、改角色、重置密码；临时密码只在弹窗显示一次；登录页支持临时密码首次登录改密。

## 改动
- `admin-web/src/pages/{dashboard,notifications,administrators,provider-editors,providers,login}.tsx`，`api/admin.ts`、`app.tsx`、`components/ui.tsx`、`format.ts`、`styles.css`。

## 验证
- PR #7 CI 全绿（`gen:api`、`typecheck`、`build`）。

## 遗留与下一步
- 回执页尚无“需人工核对”处理界面，见 T018。
- 待联调。
