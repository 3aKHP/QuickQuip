<!-- Generated from docs/dev/README.md; do not edit -->

# QuickQuip 开发者文档

本目录存放 QuickQuip 对外公开的开发契约、工程规范和架构决策记录，帮助贡献者理解代码分层、运行时边界、交付流程及重要选择的依据。

## 与本地工作区的边界

| 路径 | 是否公开 | 权威性 | 内容 |
|---|---|---|---|
| `docs/dev/` | 追踪并公开 | 现行契约；决策记录按状态与适用背景阅读 | 架构、工程规范、实现说明、决策依据、测试与发布流程 |
| 本地已忽略工作区 | 不公开 | 辅助上下文 | 计划、草稿、私有记录、沙箱、执行证据和历史归档 |

公开开发文档不得依赖本地工作区中的任何文件。私有计划形成长期规则或已发布行为时，应提炼为本目录或相应的用户/管理员文档，并移除本机路径、私有拓扑、账号、token 和其他敏感内容。

## 文档职责

| 文档 | 职责 |
|---|---|
| [`../glossary.md`](../glossary.md) | 跨文档概念名称、简短定义与领域契约入口 |
| [`adr/README.md`](adr/README.md) | 重要技术选择的背景、理由、影响、状态与替代关系 |
| [`documenting.md`](documenting.md) | 全仓公开文档规范：读者与职责、事实与证据、文风、操作示例、格式、维护与审查 |
| [`architecture.md`](architecture.md) | 目录结构、分层、依赖方向、组合根和数据/部署边界 |
| [`style.md`](style.md) | 源码结构、可维护性、类型与输入边界、错误与状态、测试和评审问题 |
| [`testing.md`](testing.md) | 测试纪律、准入与断言依据、典型反模式、合并删除和验证 |
| [`branching.md`](branching.md) | 分支模型、变更分级、验证、评审（含 KHPilot Bot Review 机制与双轨交叉核对）、发布和 hotfix 流程 |
| [`versioning.md`](versioning.md) | 主题更新、累积更新、兼容性说明、开发版本与发布候选编号 |
| [`record-identities.md`](record-identities.md) | 记录正文、共享身份、引用索引与兼容读取契约 |
| [`../admin/config-sync.md`](../admin/config-sync.md) | 配置包、共同基线、双向同步与恢复操作 |
| [`config-workspace.md`](config-workspace.md) | TOML 工作副本格式、值编码、三方计划和本地恢复事务 |
| [`llm-configuration-api.md`](llm-configuration-api.md) | LLM 配置修订、结构化交换、参数 metadata 与控制任务的 API 契约 |
| [`llm-configuration-frontend.md`](llm-configuration-frontend.md) | LLM 配置前端交付契约、用户操作、字段语义、运行状态与验收场景 |
| [`llm-module.md`](llm-module.md) | LLM 触发、上下文、记忆、provider、配置和运行时边界 |
| [`mcp-integration.md`](mcp-integration.md) | MCP 接入、协议协商、工具结果和安全边界 |
| [`mcp-tutorial.md`](mcp-tutorial.md) | MCP 概念、四种 transport 与首次接入练习导航 |
| [`skill-tutorial.md`](skill-tutorial.md) | Skill 安装、无脚本编写与完整脚本实战 |
| [`tool-discovery.md`](tool-discovery.md) | LLM 工具发现的策略、模式、限制和测试 |
| [`game-framework.md`](game-framework.md) | 游戏注册、经济系统和扩展框架 |
| [`regex-tutorial.md`](regex-tutorial.md) | 零基础正则教学（以项目规则为实例）与现行规则体系速览 |
| [`sts-formula.md`](sts-formula.md) | 杀戮尖塔公式化回复的词表与运行时说明 |

当前已实现能力、用户可见行为与配置由 `README.md`、`docs/user/`、`docs/admin/` 和 `CHANGELOG.md` 分别承担。开发文档应链接到唯一权威来源，避免在多处复制易变清单。

## 维护规则

撰写、维护和审查本目录及全仓公开文档时，遵循 [`documenting.md`](documenting.md)。文档职责、表达方式、格式、示例验证、公开信息保护与 self-docs 同步要求统一由该规范维护。
