# T005 微信支付正式接入（APIv3）

- 状态：已完成（PR #6，提交 b6a77e8；实际未引入 SDK，用 cryptography + httpx 自实现；记录见 devlog 0019）

## 目标
实现 `backend/app/integrations/payment.py` 的 `WechatPay`：JSAPI 下单（小程序支付）返回 wx.requestPayment 参数、支付通知验签与解密、退款、查询订单、关闭订单。

## 要求
- 用官方 APIv3 规范（签名：SHA256-RSA；通知：AEAD_AES_256_GCM 解密），可以引入成熟的 Python SDK（如 wechatpayv3），新增依赖写进 `backend/pyproject.toml`（CI 会自动更新 uv.lock）。
- 支付通知接口 `/api/v1/callbacks/wxpay` 的应答格式按微信要求：成功 HTTP 200/204，失败返回 `{"code": "FAIL", "message": "..."}`；需要调整 orders 模块的回调路由。
- 证书和私钥路径从配置读，不进仓库。
- 单测用录制好的样例报文（自己生成测试密钥对签名）验证验签和解密。

## 只允许改的文件
`backend/app/integrations/payment.py`、`backend/app/modules/orders/`（回调应答格式、取消订单时关单）、`backend/pyproject.toml`、对应 tests。
