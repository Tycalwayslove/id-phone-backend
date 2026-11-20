# T014 续费与订单边界

- 状态：待开始
- 依赖：T002、T003、T005；Wave 3

## 目标
补续费和加购边界规则。

## 只允许改的文件
`backend/app/modules/orders/`、`backend/app/modules/entitlements/`、对应 `backend/tests/`。

## 要求
1. 产生 `item_type=renew` 的订单，付款后延长保管期。
2. 加购付款时主权益已过期（`entitlements/service.py` 现无处理）：自动全额退款并记审计。
3. 退款按“退款中”设计，幂等（真实微信退款是异步的）。

## 验收
- 续费延期、过期加购退款、重复回调幂等均有测试；CI 全绿。
