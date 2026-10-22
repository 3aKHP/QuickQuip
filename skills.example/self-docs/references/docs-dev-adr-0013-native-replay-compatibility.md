<!-- Generated from docs/dev/adr/0013-native-replay-compatibility.md; do not edit -->

---
status: Accepted
superseded_by: []
---

# ADR-0013：按归属与结构校验选择原生回放

- 记录日期：2026-10-23
- 原始决策日期：2026-09-14（Responses 跨轮回放方案）

## 背景

执行记录可以保存协议原生状态，包括签名、加密推理和工具调用条目。将其简化为普通文字会失去部分续接信息；将保存的块直接发给另一个模型、端点或协议，又可能产生无法验证的签名、重复调用标识和不完整配对。

历史投影需要在可复用的原生信息与跨协议通用事实之间选择。

## 决定

原生回放以请求归属精确匹配和结构校验通过为前提。渠道、协议、实际请求模型、端点及协议 Profile 指纹共同确定归属；无法确认兼容性时按目标协议使用通用重建或文本档案。

Responses 在发送前检查调用标识冲突及声明、应答配对，对违规历史 Loop 降级。特定上游 HTTP 请求形状拒绝可触发一次历史推理条目降级重试；当前工具循环的原生条目按协议继续保留。

## 方案与理由

始终使用普通文本会放弃已保存的原生续接能力。无条件回放又会把协议状态的有效性建立在模型和端点恰好兼容的假设上。按归属与结构选择表达，可以在保留有效状态的同时维护工具事实。

Responses 能从执行事实重新构造通用消息；具有签名要求的协议按自身规则采用档案或其他降级。确定性错误在发送前处理，未知上游形状拒绝通过有界重试处理。

## 影响

模型、端点或能力 Profile 变化可能使历史走不同投影路径。预算精简与敏感内容检查也会影响原生回放资格，投影和重试需要使用请求副本，保留持久化事实及纪元快照。

每次真实 HTTP 尝试分别计量。错误终态、鉴权失败和普通传输失败继续按各自策略处理，历史降级重试有明确的触发条件与次数。

## 依据与相关契约

- [PR #251：Responses 跨轮原生回放](https://github.com/3aKHP/QuickQuip/pull/251)
- [当前历史投影与协议归属](../llm-module.md#42-llm-短期会话)
- [归属匹配](../../../src/quickquip/llm/provider/owner.py)、[历史投影](../../../src/quickquip/llm/history_projection.py)
- [Responses 发送前检查](../../../src/quickquip/llm/provider/openai_responses/replay_guard.py)
- [执行记录、投影与交付](0004-agent-execution-replay-delivery.md)、[纪元冻结](0003-epoch-history-freezing.md)
