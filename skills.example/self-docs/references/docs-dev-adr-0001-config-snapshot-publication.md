<!-- Generated from docs/dev/adr/0001-config-snapshot-publication.md; do not edit -->

---
status: Superseded
superseded_by:
  - 0023-online-and-offline-configuration-publication.md
---

# ADR-0001：通过不可变快照发布配置

- 记录日期：2026-10-23
- 原始决策日期：未确认；配置数据库实现于 2026-10-13 经 PR #287 合并

## 背景

Web Admin 编辑配置，Bot 在独立进程中消费配置并运行模型、工具和报告任务。并发编辑需要检查修订冲突，在途请求需要固定自己使用的配置与资源，管理员也需要观察某次修改是否已经被 Bot 接纳。

配置管理因此需要表达保存、应用和运行三个阶段，并让任务在草稿继续变化时保持确定输入。

## 决定

LLM 配置集中到 SQLite。编辑作用于带修订号的草稿，应用或探测绑定不可变配置快照，通过跨进程控制任务交给 Bot 执行。数据库记录发布版本，Bot 另行回报实际加载版本、心跳和组件状态。

认证信息保存根 `.env` 的变量引用，运行时展开；人格及多模态资产继续按各自职责维护。JSON 承担配置交换，旧 TOML 作为首次迁移输入与回退资产保留。

## 方案与理由

文件配置配合重载曾承担运行入口。配置数据库方案把修订冲突、快照、任务和运行状态放到共同的事务与任务模型中，支持 Web、CLI 和 Bot 对同一份配置协作。

草稿保存与独立应用共同保留了管理员编辑的自由度。任务绑定目标快照，使后续编辑保持与已入队任务的输入隔离；配置接纳和远端组件就绪分别回报，使失败能够定位到具体阶段。

## 影响

管理员可以保存草稿、比较版本和恢复历史，并观察发布与加载进度。在途调用继续使用已固定的配置、价格和资源代际。

开发需要维护数据库迁移、跨进程租约、任务幂等及运行状态的完整契约。配置 schema、JSON 交换版本、配置修订与项目发行版本分别管理；发布快照的不可变性也需要在后续迁移和读取中保留。

## 依据与相关契约

- [PR #287：配置数据库实现](https://github.com/3aKHP/QuickQuip/pull/287)
- [配置 API：修订、快照、任务与状态](../llm-configuration-api.md)
- [管理员配置操作](../../admin/llm-configuration.md)
- [客户端 Profile 与运行快照](0014-client-fingerprint-profiles.md)
- [配置存储](../../../src/quickquip/llm/config_store.py)、[运行时配置](../../../src/quickquip/llm/config_runtime.py)
- [配置术语](../../glossary.md#config-draft)
