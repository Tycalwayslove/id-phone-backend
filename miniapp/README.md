# 智拍证件照 小程序

Taro 4 + React 18 + TypeScript + NutUI（Taro 版）+ zustand。主要编译目标是微信小程序（weapp），同时保证 H5 能编译。接口类型从 `../docs/api/openapi.json` 自动生成，业务代码不手写接口类型。

## 目录

```
config/        Taro 配置（index / dev / prod）
types/         全局类型声明
src/api/       请求封装 client.ts 和各模块接口函数（页面里不直接写 URL）
src/stores/    zustand 状态（用户与令牌）
src/components 通用组件
src/hooks/     usePagedList（游标分页）
src/pages/     页面，每个目录 index.tsx + index.config.ts + index.scss
src/utils/     金额日期格式化、错误码文案、幂等键、路由、选图上传、保存相册
```

## 第一次运行

需要 Node 18+（建议 20）和 pnpm。

```bash
cd miniapp
pnpm install
pnpm run gen:api      # 从 ../docs/api/openapi.json 生成 src/api/schema.d.ts（生成文件不提交）
pnpm run typecheck
pnpm run dev          # 监听编译微信小程序，输出到 dist/
```

后端改了接口字段后，先在仓库里更新 `docs/api/openapi.json`，再 `pnpm run gen:api`，类型不一致会在 `typecheck` 时报错。

## 在微信开发者工具里打开

1. 打开微信开发者工具，导入项目，目录选 `miniapp/`（读取 `project.config.json`，`miniprogramRoot` 指向 `dist/`）。
2. `project.config.json` 里的 `appid` 是 `touristappid`（游客模式，JSON 不能写注释，所以说明放在这里）。游客模式下：不能真机预览部分能力、`getPhoneNumber` 和 `openType="contact"` 不可用。要测这些，换成自己的小程序 AppID。
3. 开发者工具 → 详情 → 本地设置，勾选“不校验合法域名、web-view、TLS 版本以及 HTTPS 证书”，这样才能访问 `http://localhost:8000`。

## 连接本机后端

1. 按 `docs/getting-started.md` 启动后端（`uv run uvicorn app.main:app --reload`，默认 `http://localhost:8000`），库里不配微信/支付/服务商就是 fake 模式。
2. 前端 `.env.development` 里 `TARO_APP_API_BASE=http://localhost:8000`，`pnpm run dev` 使用这份配置。
3. 真机预览时手机访问不了开发机的 `localhost`，把 `TARO_APP_API_BASE` 改成开发机局域网 IP（并让后端监听该地址）。注意 CLAUDE.md 要求数据库不对局域网开放，只开放后端端口，不要开放数据库。
4. H5 调试（`pnpm run dev:h5`）会跨域访问后端，需要后端允许 CORS。

## fake 联调怎么用

- 登录：微信小程序里 `Taro.login` 拿到的 code 发给 `POST /api/v1/auth/wechat-mini/login`；H5 没有 `wx.login`，固定用 code `dev:h5user`。后端 fake 模式下 `dev:xxx` 固定得到同一个用户。
- 支付：下单返回 `pay_params.mode = "fake"` 时，只有 `TARO_APP_FAKE_PAY=1` 才会调 `POST /api/v1/dev/orders/{order_no}/simulate-paid`，否则提示“支付未配置”。
- 回执结果：`TARO_APP_FAKE_PAY=1` 时，回执详情页底部出现“模拟结果”小按钮（completed / rejected），调 `POST /api/v1/dev/receipt-applications/{app_no}/simulate`。
- 绑定手机号：fake 模式下 code 填 `phone:13800001234`（真实的 `getPhoneNumber` 在游客模式拿不到 code）。
- 演示和测试只用假手机号、假身份证号。

## 环境变量

只读 `TARO_APP_` 开头的变量，写在 `.env.development` / `.env.production`：

| 变量 | 说明 |
|---|---|
| `TARO_APP_API_BASE` | 后端根地址，不带 `/api/v1` |
| `TARO_APP_FAKE_PAY` | `1` 开启 fake 支付和“模拟结果”按钮，生产必须为 `0` |

`pnpm run dev`（`--watch`）用 development 配置，`pnpm run build` 用 production 配置。新增变量要同步写进两个 `.env.*` 并在 `types/global.d.ts` 声明类型。

## 脚本

| 命令 | 作用 |
|---|---|
| `pnpm run gen:api` | 生成接口类型 |
| `pnpm run typecheck` | `tsc --noEmit` |
| `pnpm run build` | 构建微信小程序到 `dist/` |
| `pnpm run build:h5` | 构建 H5 |
| `pnpm run dev` | 监听编译微信小程序 |

CI 顺序：`pnpm install` → `pnpm run gen:api` → `pnpm run typecheck` → `pnpm run build`。

## 上线前要改

1. `.env.production` 里 `TARO_APP_API_BASE` 改成已备案的 https 域名，并在小程序后台“开发管理 → 开发设置”里配置 request / uploadFile / downloadFile 合法域名。
2. `project.config.json` 的 `appid` 换成正式小程序 AppID。
3. 确认 `TARO_APP_FAKE_PAY=0`。
4. 订阅消息模板 ID 由后端 `GET /notify/templates` 下发，在后台配置真实模板。
5. 配置小程序隐私保护指引（手机号、相册、相机、照片上传）。
6. tabBar 目前只有文字，上线前补图标（在 `src/app.config.ts` 加 `iconPath` / `selectedIconPath`）。

## 约定

- 接口调用只经 `src/api/*`；页面不写 URL，不手写接口类型，类型用 `components['schemas']['XXX']`。
- 令牌只放请求头，存在 Taro storage；不在日志里打印令牌、手机号、身份证号。
- 金额统一用 `PriceText` / `fenToYuan`（分转元）。
- 下单、提交回执、重提时用 `createKeyKeeper` 生成 `Idempotency-Key`，同一操作重复点击复用同一个键。
- 页面跳转路径统一用 `src/utils/nav.ts` 的 `PAGES`。
