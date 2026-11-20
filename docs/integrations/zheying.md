# 鹧应（zjzapi）回执接口对接说明

> 来源：2026-11-19 用 WebFetch 阅读 https://zjzapi.com/doc/ 下的 receipt-quick-start / receipt-make / receipt-submit / receipt-notice / receipt-resubmit / receipt-cancel / item-list / item-detail / account-info / faq，以及黔微云 https://www.qwyun.top/doc/ 的 quick-start / receipt-quick-start / receipt-make / receipt-submit / receipt-notice。
> 抓取工具只返回页面摘要，**代码示例、参数表细节、错误码表可能没拿到**，下面凡标“文档未说明”的都需向服务商确认。字段说明以官网原文为准，编码前请有人对着官网再核一遍。

## 1. 鉴权与签名

- **请求鉴权**：没有签名。每个请求的表单里带 `key`（应用 Key，在用户中心“应用管理”创建）。文档未说明有 timestamp / nonce / HMAC。
- `key` 是服务端凭证，不能放前端、日志、仓库。
- 另有 `access_token`（用户中心“账号信息”获取），**只用于** `/user/info` 查余额，回执流程不需要。
- 通用约定：HTTP 200 不代表成功，必须看 JSON 的 `code`，`0` 为成功，`msg` 为描述。
- 请求格式：POST，`application/x-www-form-urlencoded`；响应 JSON `{code, msg, data}`。图片用 Base64 原文，由表单编码器处理特殊字符，**不要二次 URL 编码**。

请求伪代码：

```python
resp = httpx.post(f"{BASE}/receipt/submit",
                  data={"key": APP_KEY, "pic_id": pic_id, "notice_url": url, "param": json.dumps(param)},
                  timeout=(5, 30))
body = resp.json()
if body["code"] != 0: raise ProviderError(body["code"], body["msg"])
```

### 回调验签（与请求鉴权不同）
- 回调表单里的 `sign` = **应用 Key 的 MD5（小写十六进制）**，是静态值。
- 验签伪代码：`hmac.compare_digest(form["sign"], md5(APP_KEY).hexdigest())`，不过则抛 `AppError(CALLBACK_SIGNATURE_INVALID)`。
- 注意：该 sign 不覆盖其他字段，无时间戳/随机数，**不防篡改、不防重放**。因此额外要求：
  1. 用 `order_no` 找到我们库里的尝试记录，找不到按未知订单处理（返回成功但丢弃，或记录告警）；
  2. 幂等处理，去重键用 `order_no + status`；
  3. 状态只允许前进（processing → 终态），终态不被覆盖；
  4. 回调 URL 里放一个我们自己生成的随机 token（路径或 query 里带 attempt_ref 的 HMAC），补足防伪造。注意 CLAUDE.md 规定“令牌绝不放 URL”指的是用户登录令牌，这里是回调校验串，建议在评审时确认是否可接受，否则只靠 order_no 校验。
  5. 日志不打印 `sign` 和 key。

## 2. 基础地址 / 测试环境

| 项 | 鹧应 | 黔微云 |
|---|---|---|
| 接口基础地址 | `https://api.zjzapi.com` | `https://api.qwyun.top` |
| 路径 | 两家相同：`/receipt/make`、`/receipt/submit`、`/receipt/cancel`、`/item/list`、`/item/get`、`/user/info` |  |

- 测试环境 / 沙箱：**文档未说明**（未发现）。需向服务商确认是否有测试 Key、免费测试规格，否则联调会真实扣费。

## 3. 流程概览

1. `POST /receipt/make`：按回执规格检测并制作照片，**免费**，返回 `pic_id`（**有效期 50 分钟**）和 `list`（如 `list.white` 图片 URL）。
2. `POST /receipt/submit`：用 `pic_id` + `notice_url` + 材料提交订单，返回 `order_no`。
3. 平台审核（约 15 分钟，办理时间 8:30–20:30 含节假日），结果推送到 `notice_url`。
4. 被驳回：`POST /receipt/submit` 带原 `order_no` + 新 `pic_id` 重新提交。
5. 未处理的订单可 `POST /receipt/cancel`。

**因此一次 `ReceiptProvider.submit` 要在适配器内部串行调用 make + submit 两个接口。** 若 make 成功、submit 超时，`pic_id` 作废即可（50 分钟过期），重试时重新 make。

## 4. 提交接口

### 4.1 `/receipt/make`
| 字段 | 必填 | 类型 | 说明 | 对应我们的入参 |
|---|---|---|---|---|
| key | 是 | string | 应用 Key | 配置 `ZHEYING_APP_KEY` |
| item_id | 是 | int | 回执规格 ID（来自 `/item/list`） | `SubmitRequest.provider_item_id`（转 int） |
| image | 是 | string | Base64 图片，≤5MB | `SubmitRequest.photo` 的 base64 |

图片要求（回执快速开始页）：JPG/JPEG/PNG，≤5MB，分辨率 <6000×6000。`photo_mime` 需为 jpeg 或 png，否则适配器应先拒绝。是否要求去掉 data URI 前缀：文档未说明，按“裸 Base64”处理。

响应 `data`：`pic_id`、`list`（含 `white` 等 URL）。

### 4.2 `/receipt/submit`
| 字段 | 必填 | 类型 | 说明 | 对应 |
|---|---|---|---|---|
| key | 是 | string | | 配置 |
| pic_id | 是 | int | make 返回，50 分钟有效 | 适配器内部 |
| notice_url | 鹧应：是；黔微云：否 | string | 回调地址，需公网可达 | 配置 `ZHEYING_CALLBACK_URL`（建议含 attempt 标识，见 1） |
| param | 否（按规格可能必填） | string(JSON) | 规格要求的额外材料；文档示例为广东驾驶证（手机号、城市、base64 身份证图片等） | `SubmitRequest.form`（姓名、身份证号等）映射成该 JSON；**键名按规格不同，文档未给全表** |
| is_print | 否 | int | 1=打印邮寄，0/不传=不邮寄 | 首版固定不传 |
| print_param | is_print=1 时必填 | string(JSON) | 收件人姓名、电话、省、市、区、地址 | 首版不用 |

响应：`code=0`，`msg="提交成功"`，`data.order_no`（文档示例为 20 位数字字符串，参数表写 int，**一律按字符串存**）→ `submit()` 的返回值。

`attempt_ref`、`region_code`：接口**没有**对应字段，服务商回调只带 `order_no`。因此必须在提交成功后立刻保存 `order_no ↔ attempt_ref`。若 submit 超时（结果未知），无法用 attempt_ref 反查，见第 9 节。

### 4.3 重新提交
`/receipt/submit` 额外带 `order_no`（上次订单号）。是否沿用原订单号、是否再次计费：文档只写“完成时 7 元/单”，未说明驳回重提是否重复收费。我们的业务若“驳回后用户修改再提交”，需决定是新建 attempt 并带旧 order_no，待确认。

## 5. 查询接口

**文档未说明**：已阅读的页面里没有“订单查询”接口（只有 make / submit / resubmit / cancel / 规格列表 / 规格详情 / 账号信息）。导航栏页面列表中也没有 query。

影响：`ReceiptProvider.query()` 目前无法实现真实查询。可选方案：
- A. 仅依赖回调；`query()` 抛 `NotImplementedError` 或返回 `processing`，由业务层对长时间无回调的订单走人工/客服核对；
- B. 向服务商确认是否有未公开的查询接口（强烈建议先问）。

## 6. 回调（订单状态通知）

- `POST`，`application/x-www-form-urlencoded`（不是 JSON）到 `notice_url`。
- 字段：

| 字段 | 必有 | 说明 |
|---|---|---|
| order_no | 是 | 订单号 |
| status | 是 | 见下表 |
| sign | 是 | 应用 Key 的 MD5 |
| image_receipt | status=3 | 回执照片 URL |
| image | status=3 且照片被调整 | 证件照 URL |
| image_print | status=3，仅广东驾驶证、港澳通行证 | 排版照 URL |
| reject_msg | status=-1 | 驳回原因 |
| logistics_info | status=4 | 数组，含 `express_name`、`express_no` |

- 我们的响应：处理成功后返回 `{"data": {}, "code": 0, "msg": "同步完成"}`；保存失败不要返回成功（服务商据此判断是否重推）。
- 重试策略（次数、间隔）、超时时间、回调源 IP：**文档未说明**。
- 回执图片是 URL，需要我们下载转存到自己的 OSS（`ProviderStatus.receipt_image` 为 bytes）。URL 有效期**文档未说明**，收到回调后应尽快下载。下载失败不要让回调返回失败，应异步重试。
- `official_expire_at`（回执有效期）：回调里**没有**该字段，文档未说明，需另想办法（按规格配置固定天数，或向服务商确认）。
- `image_code`（回执图像号）：回调里**没有**，可能只在回执图片上，文档未说明。

## 7. 状态映射

| 服务商 status | 含义 | 我们的 result | 说明 |
|---|---|---|---|
| 2 | 审核中 | processing | |
| 3 | 办理完成 | completed | 取 `image_receipt` |
| 4 | 已打印邮寄 | completed（若未启用邮寄则不会出现） | 首版不开邮寄；收到按“已完成后的附加事件”处理，不改变 completed，只记录物流 |
| -1 | 审核失败/驳回 | rejected | `reject_reason` = `reject_msg` |
| -2 | 取消完成 | failed | 我们主动取消的结果；业务层按“已取消”处理 |
| 接口 `code != 0`（make/submit 阶段） | 业务拒绝 | 不产生 result，抛业务异常 | 见第 8 节 |
| 网络超时 | 结果未知 | 抛 `TimeoutError` | 不当失败 |
| 其他未知 status | | processing + 告警 | 不要丢弃，也不要当终态 |

“failed”在我们这边的语义是“服务商侧无法办理/技术失败”；鹧应文档里没有单独的“系统失败”状态，需确认 -1 是否也包含系统异常（见待确认）。

## 8. 错误码

- 所有接口 `code=0` 成功。
- 已确认的零散码：黔微云 quick-start 提到 `1008` 表示 `access_token` 无效（需在账号信息页重置）。
- **完整错误码表：文档未说明**（FAQ、account-info 页均无）。FAQ 只给了排查建议：Key 不完整、应用未启用、应用无该接口权限、Key 不属于当前账号。
- 适配器策略：`code != 0` 统一包成内部异常，保存 `code`、`msg`；余额不足、Key 无效、规格不存在等需要告警的类别，等拿到错误码表后再细分。

## 9. 费用

- `/receipt/make`、`/item/list`、`/item/get`：免费。
- `/receipt/submit`：**7 元/单，办理完成时计费**；打印邮寄再加 7 元。
- 失败/驳回/取消是否收费：文档未明确说明（“完成时计费”暗示不收，需确认）。驳回重提是否再收 7 元：文档未说明。
- 余额不足时 submit 的表现：文档未说明。
- 黔微云：价格与鹧应相同（7 元，邮寄 +7 元）；quick-start 的“计费说明”章节页面抓取未包含。
- 我们的零售价、成本入库：金额一律整数分，成本 700 分/单（待确认）。

## 10. 限流

文档未说明（FAQ、account-info 均无）。`/user/info` 数据有 10 分钟延迟，`day_make`（今日调用次数）可看。建议适配器自带并发上限（如同一服务商并发 ≤5），并向服务商确认 QPS。

## 11. 超时与重试建议

- 连接超时 5s，读超时：make 30s（含图片上传，≤5MB），submit 30s，cancel 10s。（官方未给建议值，均为我们的假设。）
- **make 超时**：可安全重试（免费，无副作用）。
- **submit 超时**：结果未知，**不要自动重试 submit**（可能重复下单收 7 元）。抛 `TimeoutError`，业务层标记“未知”。没有查询接口、submit 也没有幂等键（文档未说明），所以必须人工/向服务商核对，或等回调（回调带 order_no，但我们没有 order_no 无法关联——需要和服务商确认能否支持自定义外部单号）。
- **cancel**：仅对“待处理”订单有效；返回 code != 0 视为不可取消，等最终状态。
- 业务层不要在 08:30–20:30 之外承诺“15 分钟出结果”：提交时间在办理时段外，订单会等到次日；需在前端提示。
- 回调接收端必须快速返回（下载图片异步做）。

## 12. 配置项（环境变量，同步写进 `.env.example`）

| 变量 | 说明 | 示例 |
|---|---|---|
| ZHEYING_BASE_URL | 接口基础地址 | `https://api.zjzapi.com` |
| ZHEYING_APP_KEY | 应用 Key，同时用于回调验签（MD5） | |
| ZHEYING_CALLBACK_URL | 对外可达的回调地址（`notice_url`） | `https://<域名>/api/v1/callbacks/receipt/zheying` |
| ZHEYING_TIMEOUT_SECONDS | 读超时秒数 | 30 |

`ZHEYING_APP_SECRET` 不需要：接口只有一个 `key`，没有单独的 secret。黔微云对应 `CLIPIMG_*`（或 `QWYUN_*`，按 T004 的 clipimg 适配器命名）：`BASE_URL=https://api.qwyun.top`，`APP_KEY`。
`/user/info` 的 `access_token` 仅在要做余额监控时才加配置 `ZHEYING_ACCESS_TOKEN`。

## 13. 与黔微云的差异

两家路径、参数、状态码、7 元计费、办理时间、图片限制、回调格式一致，基本是同一上游。已发现的差异：

| 项 | 鹧应 | 黔微云 |
|---|---|---|
| 基础域名 | api.zjzapi.com | api.qwyun.top |
| `notice_url` | 必填 | 选填；不填则只保存订单，不推送通知 |
| 回调 status 表 | 2、3、4、-1、-2 | 回调页 2、3、4、-1、-2；快速开始页只列 2、3、-1、-2 |
| 回调 sign | MD5(应用 Key) | 同，明确为小写十六进制 |
| 计费说明 | 提交页明写 7 元 | 提交页同样写 7 元（快速开始页未列） |
| `order_no` 类型 | 回调/响应示例为字符串，参数表为 int | 回调页为 string |

其余差异文档未说明；其他页面（cancel / resubmit / faq）黔微云未逐页对比，编码前建议再核对。适配器可抽一个共用基类，仅 base_url / key 不同。

## 14. 待向服务商确认的问题清单

1. 是否有测试环境/沙箱 Key？联调是否会真实扣费？
2. 是否有订单查询接口？若无，回调丢失时如何核对订单状态？
3. 回调重试策略（次数、间隔、超时）？回调源 IP 是否固定？
4. 回调签名是否确实只有静态 `MD5(key)`？能否提供 HMAC / 时间戳版本？
5. submit 是否支持幂等键或自定义外部单号（我们的 `attempt_ref`）？超时后如何避免重复下单？
6. 完整错误码表（尤其余额不足、规格不存在、pic_id 过期、重复提交、Key 无效）？
7. 费用：驳回、取消、失败是否收费？驳回重提是否再收？是否可预付/对账单？
8. -1“审核失败”是否包含系统异常？是否有“可重试”与“不可重试”的区分？
9. 各规格 `param` 的字段表（键名、类型、必填、身份证图片是否 base64、大小限制）？`/item/get` 是否能返回这些要求？
10. 回执图片 URL 的有效期？是否需要鉴权？`image_code`（图像号）、`official_expire_at`（回执有效期）如何获取？
11. 限流（QPS、并发、日调用量）？
12. 办理时段外（20:30 后）提交的订单如何处理，SLA 是多少？是否提供“当前是否在办理时段”的接口？
13. 驳回重提（带 `order_no`）是沿用同一订单号还是生成新订单号？重提次数限制？
14. 两家（鹧应、黔微云）是否共用库存/账户余额与订单？订单是否互通？
15. `pic_id` 50 分钟有效，是否可重复用于多次 submit？
16. `cancel` 在“审核中(status=2)”是否可用？“待处理”的准确定义？
17. 是否支持直接上传已制作好的照片跳过检测/制作（我们本地已按规格导出）？

## 15. 实现说明

- 真实模式按 `providers.adapter` 的 `zheying`、`clipimg` 选通道，分别使用当前配置的 `ZHEYING_API_BASE`、`ZHEYING_APP_KEY` 和 `CLIPIMG_API_BASE`、`CLIPIMG_APP_KEY`。部署黔微云时将 `CLIPIMG_API_BASE` 设为 `https://api.qwyun.top`。回调地址由 `PUBLIC_BASE_URL` 和服务商记录的 code 拼成，默认每次提交生成随机 nonce。
- 提交以表单串行调用 make、submit，请求凭据为 `key`。图片发送裸 Base64，按编码后不超过 5 MB 处理，由 make 检查分辨率。连接超时 5 秒，读写超时 30 秒。每阶段只调用一次。返回明确的非零 `code` 时抛 `PROVIDER_UNAVAILABLE`，异常使用固定说明以免回显 `msg` 中的凭据或办理材料。任一阶段超时，或 submit 的响应无法确认单号和结果时，抛出 `TimeoutError`。
- `param` 的键名按规格变化。业务层需按 `ProviderSpec.param_mapping` 映射表单，再传入 `SubmitRequest.form`。适配器将传入的非空表单转成 JSON，并省略打印邮寄参数。
- `build_callback_url(url)` 返回带 nonce 的 URL 和 nonce。接入时，receipts 在发单前持久化 nonce 摘要并绑定 attempt，将对应 nonce 通过 `get_provider(..., callback_nonce=nonce)` 传给此 attempt 的适配器。回调入口需读取 URL 参数，在落库前校验摘要、服务商和订单归属，并按单号与原始状态去重。同步保存提交返回的 `order_no`。若 submit 超时，可在验签和 nonce 校验通过后，将回调单号绑定到尚无单号的同一 attempt。应用状态只允许合法迁移，完成后的物流通知单独补存。处理成功后返回第 6 节的 JSON 响应。接入时同步处理应用服务器与反向代理访问日志中的 nonce 脱敏。
- 回调使用常量时间比较验证小写 MD5 签名。状态 3 的 `raw["image_receipt"]` 提供下载地址，由 receipts 在校验归属后排队下载并转存，下载失败由后台任务补偿。图像号和官方有效期保留为空。状态 4 的 `raw["logistics_info"]` 提供承运商和运单号。物流的表单编码未说明，适配器接受 JSON 数组、单个 JSON 对象及方括号字段。
- 查询恒返回 `processing`。poller 需对真实通道的 `submitted`、`processing`、`unknown` 设置人工核对截止时间，可从 `submitted_at`（缺失时从 `created_at`）起算 2 小时。到期后标记后台待核对并清空 `next_poll_at`，仍允许处理已验证的迟到回调。
- 服务商仍需确认沙箱、限流、回调重推策略及来源 IP、幂等与外部单号、完整错误码与余额不足行为、异常和重提的计费及订单号、`pic_id` 复用、办理时段外 SLA、图片链接有效期与鉴权。实现采用单次提交、驳回状态统一映射、按原始事件去重的处理方式。回调 IP 白名单及单独的回调地址和超时配置可在业务接入时补充。
