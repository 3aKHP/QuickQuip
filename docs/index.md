<p align="center">
  <img src="assets/brand-mark.svg" width="64" alt="QuickQuip" />
</p>

# QuickQuip 文档导航

QuickQuip 是一个基于 NoneBot2 + OneBot V11 的规则驱动优先 QQ 群聊机器人，在精心设计的正则匹配和状态机之上，支持按群启用 LLM 扩展。

本文档目录帮你按角色快速找到需要的信息。

---

## 用户手册（群友阅读）

| 文件 | 说明 |
|------|------|
| [user/group-commands.md](user/group-commands.md) | 群内指令速查——AI 对话、联网搜索、故障机器人转写、贴吧搬运、每日总结等全部命令，含常见问题 |
| [user/group-games.md](user/group-games.md) | 群内游戏指南——数字炸弹、21点、俄罗斯轮盘、牛牛大作战玩法和命令速查 |
| [user/llm-tool-discovery.md](user/llm-tool-discovery.md) | AI 工具发现说明——为什么机器人有时会先找工具，再调用外部能力回答 |
| [user/private-commands.md](user/private-commands.md) | 私聊指令速查——会话管理、AI 配置、记忆管理，群聊 vs 私聊功能对比 |
| [user/three-kingdoms-memes.md](user/three-kingdoms-memes.md) | 新三国梗触发指南——内置电视剧彩蛋的触发词、语境条件和限流说明 |

## 管理手册（部署者/管理员阅读）

| 文件 | 说明 |
|------|------|
| [admin/deployment.md](admin/deployment.md) | 云端部署指南——服务器选型、Docker Compose 编排、LLBot 登录、贴吧登录态、Web Admin 反代、日常维护与排障 |
| [admin/configuration.md](admin/configuration.md) | 完整配置参考——`.env` 环境变量、`llm.toml`、`generation.toml`、`awakening.toml`、`chat_rules.toml`、`games.toml`、`sensitive_words.toml`、`personas/` 所有可配项 |
| [admin/tool-discovery.md](admin/tool-discovery.md) | LLM 工具发现配置——大量 MCP 工具接入时的 `tool_search`、`tool_list`、常驻工具和排障建议 |
| [admin/game-config.md](admin/game-config.md) | 游戏系统管理——游戏开关、参数配置、数据库文件、故障排查 |
| [admin/sensitive-filter.md](admin/sensitive-filter.md) | 敏感词过滤器——词表配置、接入点、日志与测试方法 |
| [admin/migration-napcat-to-llbot.md](admin/migration-napcat-to-llbot.md) | NapCat 迁移 LLBot——Compose 服务、OneBot 连接方式、回退步骤 |
| [admin/web-admin.md](admin/web-admin.md) | Web 管理后台——鉴权结构、Session 管理、反向代理配置、日志/Trace/各标签页功能列表 |

## 开发手册（开发者阅读）

| 文件 | 说明 |
|------|------|
| [docs/dev/style.md](../docs/dev/style.md) | 代码规范与架构硬原则——单一职责、文件长度预警、分层纪律、抽取触发条件、反模式与重构节奏 |
| [docs/dev/branching.md](../docs/dev/branching.md) | 分支模型与发布流程——精简 GitFlow、日常工作流、Release checklist、hotfix 例外 |
| [docs/dev/architecture.md](../docs/dev/architecture.md) | 项目架构与结构——三层架构、消息流、目录用途、分发层/自用层划分、gitignore 规则 |
| [docs/dev/game-framework.md](../docs/dev/game-framework.md) | 游戏框架开发指南——BaseGame 接口、economy API、Session 模式 vs RPG 模式、扩展新游戏步骤 |
| [docs/dev/llm-module.md](../docs/dev/llm-module.md) | LLM 模块详解——触发规则、上下文边界、人格注入设计、配置说明、群内命令、部署注意事项 |
| [docs/dev/mcp-integration.md](../docs/dev/mcp-integration.md) | MCP 集成约定——transport 选择、Docker Socket 取舍、推荐架构、现有 MCP server 列表 |
| [docs/dev/regex-tutorial.md](../docs/dev/regex-tutorial.md) | 正则表达式教程——从零开始，以项目实际规则为例，覆盖基础语法到进阶特性 |
| [docs/dev/tool-discovery.md](../docs/dev/tool-discovery.md) | LLM 工具发现实现说明——manifest、动态加载循环、模式语义和测试覆盖 |

---

## 其他项目文档

| 文件 | 说明 |
|------|------|
| [../README.md](../README.md) | 项目入口——功能亮点与快速开始 |
| [../ROADMAP.md](../ROADMAP.md) | 演进路线——版本锁定 scope 与中长期方向 |
| [../CHANGELOG.md](../CHANGELOG.md) | 变更记录——按 Keep a Changelog 规范维护 |
