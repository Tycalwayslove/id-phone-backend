# ADR 0001 模块化单体 + 四层分层

- 状态：已采纳（2026-11-19）

## 背景
一个人开发和维护，后续有多端、多服务商、私域运营。

## 决定
一个后端服务、一个 PostgreSQL；内部按业务模块（auth、users、specs、photos、orders、entitlements、receipts、notify、admin）划边界。模块内 router → service → repo → models；外部服务只经 integrations 适配器；模块之间只调对方 service（约定见 `backend/app/modules/CONTRACTS.md`）。

## 理由
微服务的部署、调用链、数据一致性成本一个人扛不住；边界清楚的单体以后哪个模块需要拆出去也拆得动。

## 代价
所有模块共享一个库和一个进程，某个模块的慢查询会影响全局，靠索引和监控兜住。
