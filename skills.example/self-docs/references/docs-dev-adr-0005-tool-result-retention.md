<!-- Generated from docs/dev/adr/0005-tool-result-retention.md; do not edit -->

---
status: Accepted
superseded_by: []
---

# ADR-0005：区分临时查询结果与可保留工具事实

- 记录日期：2026-10-23
- 原始决策日期：2026-09-05

## 背景

Agent 执行记录需要保存工具调用事实，以支撑跨轮历史回放、消息交付核对与异常恢复。然而部分只读查询工具（如检索近期聊天、历史归档或群语录）返回的正文在自身数据源中已有权威留存；若把每次检索出的原文副本持续写入会话库，不仅会让会话存储混入额外归档副本，还会迅速推高后续轮次的重放上下文开销。

因此，工具执行记录需要区分常规工具结果的有界持久化与临时查询结果的当轮消费边界。原始模型请求与响应的排障留档由独立的 HTTP Trace 按诊断开关承担，不占用业务会话库。

## 决定

为工具调用结果定义两档显式保留策略：

- `bounded`：在业务记录的体积与生命周期约束内保留经过清洗的工具结果正文，供后续轮次跨轮回放复用。
- `ephemeral`：查询结果正文仅在当前 Agent Loop 内供模型推理消费；循环结束后，业务记录保留工具调用结构、执行状态与明确的省略标记，不再落库保存结果正文、分页游标或请求内命中明细。

省略正文后的历史回放仍如实表达该工具曾被调用及其成功、失败或中断状态。协议原生状态块（如包含完整工具输出条目的原生响应副本）同样服从该保留边界，一旦当轮触达 `ephemeral` 工具即停止跨轮原生保留，避免临时查询原文经由原生状态旁路落库。

## 方案与理由

早期讨论曾考虑用附加记录侧表保存检索过程，或直接把检索结果纳入常规会话压缩。由于全量群聊消息与语录已由各自领域存储独立维护（见 [ADR-0007](0007-unified-chat-archive.md)），在 `llm.db` 中重复保存检索副本既缺乏增量事实价值，又会挤占正常对话的历史窗口预算。将查询正文定为 `ephemeral` 并保留结构化调用回执，能够在不丢失“模型查过什么、结果是否成功”的前提下守住会话库的职责边界与重放成本。

## 影响

工具定义与执行记录器之间需要显式声明并传递保留策略与参数脱敏规则；存储层、协议原生状态保存与跨轮历史投影需协同遵守同一边界。排查单次临时查询向模型实际输入了哪些原文时，管理员可通过开启 HTTP Trace 查看当轮原始报文。

## 落地核对

提交 `7a11405` 先行在存储层实现了 `EPHEMERAL` 与 `BOUNDED` 枚举及结果正文省略逻辑。2026-11（[Issue #72](https://github.com/3aKHP/QuickQuip/issues/72) 及后续扩展）完成了从工具注册元数据（`result_retention` 与 `redact_arguments`）、工具循环传递到执行记录器的全链路接线：声明了参数脱敏的工具仅按白名单持久化查询模式、分页偏移、时间范围或引用计数等结构化字段，不落库原始关键词与发言人文本；当轮一旦调用 `ephemeral` 工具，协议原生副本仅在内存中维持至当前 Agent Loop 结束，落库时整轮省略并标记 `NativeOmissionReason.EPHEMERAL_POLICY`。现已接入 `ephemeral` 策略的工具涵盖近期消息检索 `search_recent_messages`、群历史查询工具组（[ADR-0027](0027-history-investigation-executor.md)）以及只读群语录查询工具 `query_group_quotes`。

## 依据与相关契约

- [PR #213：Agent Loop 实现](https://github.com/3aKHP/QuickQuip/pull/213)、[PR #341：群历史查询与 ephemeral 全链路接线](https://github.com/3aKHP/QuickQuip/pull/341)、[PR #377：群语录只读查询工具](https://github.com/3aKHP/QuickQuip/pull/377)
- [保留策略类型](../../../src/quickquip/llm/agent_records.py)、[存储的结果保留处理](../../../src/quickquip/llm/store_parts/agent_records.py)
- [工具循环入口](../../../src/quickquip/llm/tool_loop.py)、[记录器策略接线](../../../src/quickquip/llm/service_parts/agent_runtime.py)
- [HTTP Trace 职责](../llm-module.md#1-模块定位)
- [群历史查询与专用调查执行器](0027-history-investigation-executor.md)、[MCP 内容进入模型的归一化边界](0018-mcp-result-normalization.md)
- [临时检索结果术语](../../glossary.md#ephemeral-result)
