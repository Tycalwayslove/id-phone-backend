# 文档地图

这个目录是项目的“记忆”。换人维护、换电脑、开新的 AI 会话，都先从这里读起。

| 想知道 | 看哪里 |
|---|---|
| 项目规则（分层、接口、迁移、安全、工作方式） | 仓库根目录 `CLAUDE.md` |
| 产品要做什么、业务规则 | `docs/product/requirements.md` |
| 现在做到哪了、下一步做什么 | `docs/progress.md` |
| 每次需求怎么拆、改了什么、怎么验证的 | `docs/devlog/`（按编号从旧到新） |
| 为什么这么设计（重要决定） | `docs/adr/` |
| 本机怎么跑起来 | `docs/getting-started.md` |
| 怎么部署、怎么把数据库搬到服务器 | `docs/deploy.md` |

## 更完整的设计文档

需求、数据库设计（含 ER 图）、架构规范、登录与权限设计最早写在 Claude Doc 里：
<https://claude.ai/artifact/U8cz9oRTJQfYE8jzSVe5fe>

各标签页：需求定义 v0.3、数据库设计、后端上手手册、架构与项目规范、登录与权限设计。

仓库里的文档是精简版，足够让人和 AI 理解项目并继续开发；两边有出入时，以仓库里的代码和本目录为准，并把 Claude Doc 同步更新。

## 记录的规矩

每完成一项需求（哪怕很小），都要：

1. 在 `docs/devlog/` 新建一篇，格式见 `docs/devlog/README.md`。
2. 更新 `docs/progress.md`。
3. 做了影响长期的设计决定，在 `docs/adr/` 记一篇。
