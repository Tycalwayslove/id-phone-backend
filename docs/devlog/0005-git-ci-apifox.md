# 0005 Git、CI 与 Apifox 自动同步

- 日期：2026-11-19
- 状态：已完成
- 相关提交：c6f09c4、92762b6

## 需求
“git 仓库已经建立了，推送下。”“Apifox 有没有 MCP 可以直接写入和导入？我不想更新的时候自己生成 json 再导入。”“后续全程由你写代码并且提交。”

## 方案与决定
- Apifox 官方 MCP 只读（给 AI 读文档），不用 MCP；改为 CI 在推送到 main 后导出 OpenAPI，调用 Apifox 开放接口 `import-openapi` 写入。密钥放 GitHub Secrets（APIFOX_ACCESS_TOKEN、APIFOX_PROJECT_ID）。
- 推送：用户安装 Claude GitHub App 授权本仓库后由 AI 推送。AI 在用户 Mac 的仓库里提交，通过 git bundle 转到云端环境推送。

## 验证
首次同步 Apifox 返回 endpointCreated=1。
