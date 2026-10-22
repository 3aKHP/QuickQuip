<!-- Generated from docs/dev/adr/0002-business-session-identity.md; do not edit -->

---
status: Accepted
superseded_by: []
---

# ADR-0002：由业务维护 Session 身份

- 记录日期：2026-10-23
- 原始决策日期：2026-10-13

## 背景

一次持续聊天可以跨越多次用户触发、工具续轮、模型切换和上下文缩窗。客户端 Profile 又需要把交互身份投影到请求头、Body 或缓存键。身份的创建与结束边界需要由业务连续性决定，才能让出口请求保持一致归属。

## 决定

业务入口建立并维护稳定的 Session 身份。聊天在明确的新建、清空或结束操作处管理绑定；冷场、历史裁剪、模型或人格切换、重试和服务重启延续所属身份。可恢复存档保留其身份。

Scope 管理设置和历史入口，Epoch 管理上下文窗口。独立任务使用自己的短任务 Session。请求携带不可变身份快照，Profile 根据该输入完成出口投影；写入有效性继续由 generation 等屏障校验。

## 方案与理由

已确认的业务边界选择显式清空或新开作为结束来源，并将冷场和窗口裁剪保留为上下文管理动作。这样，窗口为容量或缓存策略推进时，持续交互仍有相同业务归属。

客户端投影在身份契约确定后实现，具体 UUID 形态、协议字段和模板版本由出口层管理。入口因此可以按业务维护续接关系，协议选择与 HTTP 重试沿用该关系。

## 影响

持续聊天、独立任务和请求尝试有可辨认的归属。存档恢复、服务重启和协议投影可以复用已保存的身份。

会话迁移、归档与写入屏障需要在事务中协作；清空后的迟到结果必须经过有效性检查。新增调用入口需要明确选择聊天身份或任务身份，并显式向下传递快照。

## 依据与相关契约

- [PR #288：Session 生命周期](https://github.com/3aKHP/QuickQuip/pull/288)
- [Session、纪元与历史契约](../llm-module.md#42-llm-短期会话)
- [请求身份投影](../../admin/client-fingerprints.md)
- [客户端 Profile 的职责选择](0014-client-fingerprint-profiles.md)
- [业务身份类型](../../../src/quickquip/llm/session.py)、[持久化生命周期](../../../src/quickquip/llm/store_parts/session_lifecycle.py)
- [业务会话术语](../../glossary.md#session)
