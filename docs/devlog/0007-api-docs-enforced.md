# 0007 接口文档写全并强制检查

- 日期：2026-11-19
- 状态：已完成
- 相关提交：19cdc8e

## 需求
“接口参数和返回值这些做好参数的注释，不然接口文档上面都没有啥信息。”

## 方案与决定
- 写法要求写进 CLAUDE.md（中文说明、每个字段 description 和 examples、错误码声明）。
- `scripts/check_api_docs.py` 在 CI 里检查：接口缺 summary/description/operation_id/response_description，参数或字段缺 description，模型缺 docstring，都会失败，且不会同步到 Apifox。
- 未写 operation_id 的路由会被打上 MISSING_OPERATION_ID 标记，从而被查出。

## 验证
CI 检查通过，Apifox 新增健康检查和错误模型说明。
