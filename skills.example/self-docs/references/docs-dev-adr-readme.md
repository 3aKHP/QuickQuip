<!-- Generated from docs/dev/adr/README.md; do not edit -->

# 架构决策记录

本目录面向开发维护者，记录重要技术选择的背景、理由和代价。查阅当前行为与操作时，从[开发文档索引](../README.md)进入相应契约；理解概念名称时使用[项目术语表](../../glossary.md)。

## 决策索引

### 架构与数据

| 编号 | 决策 | 状态 | 替代记录 |
|---|---|---|---|
| [ADR-0006](0006-layered-architecture-composition.md) | 按领域分层并由应用层装配 | Accepted | — |
| [ADR-0007](0007-unified-chat-archive.md) | 统一群聊归档并按消费方序列化 | Accepted | — |
| [ADR-0008](0008-record-content-member-identity.md) | 分离记录正文、成员关联与展示名称 | Accepted | — |
| [ADR-0021](0021-configuration-runtime-storage-separation.md) | 先分离配置与运行数据，再重构本地配置工具 | Accepted | — |

### 权限与部署

| 编号 | 决策 | 状态 | 替代记录 |
|---|---|---|---|
| [ADR-0009](0009-web-admin-server-sessions.md) | 通过服务端会话保护管理接口 | Accepted | — |
| [ADR-0010](0010-global-admin-registry.md) | 由项目注册表维护全局管理员 | Accepted | — |
| [ADR-0011](0011-transactional-deployment-recovery.md) | 以事务部署版本并保留共享运行数据 | Accepted | — |
| [ADR-0025](0025-tracked-operations-programs.md) | 统一分发运维程序并分离生产配置 | Accepted | — |

### 配置、会话与模型请求

| 编号 | 决策 | 状态 | 替代记录 |
|---|---|---|---|
| [ADR-0019](0019-configuration-three-way-sync.md) | 通过共同配置基线协调双向同步 | Superseded | [ADR-0024](0024-directional-configuration-deployment.md) |
| [ADR-0020](0020-editable-configuration-workspaces.md) | 以持久 TOML 工作副本编辑配置包 | Superseded | [ADR-0022](0022-local-configuration-workspace-cli.md) |
| [ADR-0022](0022-local-configuration-workspace-cli.md) | 以 qqconf 统一编辑本地持久化配置 | Superseded | [ADR-0024](0024-directional-configuration-deployment.md) |
| [ADR-0001](0001-config-snapshot-publication.md) | 通过不可变快照发布配置 | Superseded | [ADR-0023](0023-online-and-offline-configuration-publication.md) |
| [ADR-0023](0023-online-and-offline-configuration-publication.md) | 通过不可变快照完成在线与停服发布 | Accepted | — |
| [ADR-0024](0024-directional-configuration-deployment.md) | 工作副本与单向配置部署 | Accepted | — |
| [ADR-0002](0002-business-session-identity.md) | 由业务维护 Session 身份 | Accepted | — |
| [ADR-0003](0003-epoch-history-freezing.md) | 在纪元内冻结历史表达 | Accepted | — |
| [ADR-0012](0012-static-prefix-turn-envelope.md) | 将动态轮次信息放入当轮信封 | Accepted | — |
| [ADR-0013](0013-native-replay-compatibility.md) | 按归属与结构校验选择原生回放 | Accepted | — |
| [ADR-0014](0014-client-fingerprint-profiles.md) | 以客户端 Profile 组织出口请求特征 | Accepted | — |

### 执行、工具与扩展

| 编号 | 决策 | 状态 | 替代记录 |
|---|---|---|---|
| [ADR-0004](0004-agent-execution-replay-delivery.md) | 分离执行记录、历史投影与消息交付 | Accepted | — |
| [ADR-0026](0026-conversation-owned-memory.md) | 由主对话模型维护会话记忆 | Accepted | — |
| [ADR-0005](0005-tool-result-retention.md) | 区分临时查询结果与可保留工具事实 | Accepted | — |
| [ADR-0015](0015-progressive-skill-loading.md) | 通过工具调用渐进加载 Skill 内容 | Accepted | — |
| [ADR-0016](0016-trusted-skill-execution.md) | 由部署者管理受信任 Skill 并约束脚本执行 | Accepted | — |
| [ADR-0017](0017-preset-skill-distribution.md) | 保留可选 Skill 副本并显式检测和同步漂移 | Accepted | — |
| [ADR-0018](0018-mcp-result-normalization.md) | 将 MCP 结果归一化为受控内部内容 | Accepted | — |

## 何时记录

影响模块依赖、状态所有权、持久化、跨进程协作、协议兼容或后续开发约束的重要选择，使用 ADR 保留依据。局部实现和修复在 PR 中说明。提案可以先在 Issue 讨论，决定成形后关联 ADR 与实现变更。

每篇围绕一个决定，使用[模板](template.md)记录背景、决定、候选方案、理由、影响和公开依据。按记录创建顺序分配四位编号，文件名采用 `NNNN-short-title.md`，编号不复用，文件名保持稳定。原始决定的日期与本次记录日期分别填写；无法核实的原始决策日期标为“未确认”。

补录从当时确认的方案、合并记录和当前契约核对事实。候选方案只记录确有依据的讨论；内部材料中的来源映射留在内部工作区，公开记录完整解释必要背景并引用可公开访问的依据。

## 状态与维护

| 状态 | 含义 |
|---|---|
| `Proposed` | 方案待决策 |
| `Accepted` | 方案已获接受，实现进度由关联 Issue、PR 与当前契约说明 |
| `Rejected` | 方案讨论后未采用，保留其理由 |
| `Superseded` | 决定已由其他 ADR 替代，沿替代链接查阅后续决定 |

编号 ADR 在文件开头使用 YAML front matter：`status` 必填，`superseded_by` 为同目录 ADR 文件名列表，缺省为空。`Superseded` 必须列出有效替代记录；其他状态的替代列表为空。目录说明与模板按各自用途阅读。

已接受决定发生实质变化时新增 ADR，并更新旧记录的状态、替代链接和本页索引。文字、日期证据和引用可在原记录修正，保留历史选择及其当时背景。文稿复审进度放在交付或评审记录中。

本目录全文随 self-docs 同步，生成索引显示状态与替代关系。状态元信息或替代引用无效时，同步工具报错。修改源文档后按[文档维护规范](../documenting.md#维护与审查)生成并检查副本。
