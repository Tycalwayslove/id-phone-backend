# 0002 数据库设计

- 日期：2026-11-18
- 状态：已完成

## 需求
“数据库先分析业务访问模式，再设计表结构，并且需要展示关联关系，方便我查看是否存在问题。”

## 拆解
1. 列出访问模式（谁在什么场景查什么、多频繁）。
2. 按域设计 28 张表：用户与私域、规格与服务商、照片与文件、套餐订单权益、回执、通知与后台。
3. 画 ER 图（4 张：用户与订单、规格与服务商、照片、回执），检查外键和环。

## 方案与决定
- 回执两层：申请（receipt_applications）+ 每次提交（receipt_attempts）。用 `is_current` + 部分唯一索引代替 current_attempt_id，避免两表互相外键。
- 回调先落库再处理，`dedupe_key` 去重；状态只前进不后退；超时不当失败。
- 权益：entitlements + entitlement_quotas（total/used，CHECK used<=total）+ entitlement_ledger（预占/确认/释放，唯一约束保证幂等）。
- 规范：状态用 CHECK 约束不用枚举；金额整数分；时间 timestamptz；外键都写 ondelete 并建索引；约束统一命名。
- 文件命名规则见 `docs/product/requirements.md`。

## 改动
`backend/app/models/*.py`；ER 图在 `Claude outputs/fig_A~D.svg`；完整说明见 Claude Doc「数据库设计」。

## 遗留
无。
