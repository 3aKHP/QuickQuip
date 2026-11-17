<!-- Generated from docs/dev/adr/0031-standalone-search-evidence.md; do not edit -->

---
status: Accepted
superseded_by: []
---

# ADR-0031：由客户端执行搜索并保存可回放材料

- 记录日期：2026-11-17
- 原始决策日期：2026-11-17

## 背景

Responses hosted 搜索返回的调用条目和来源清单可能没有网页正文。后续无状态请求需要已经保存的检索材料才能回答原文细节。搜索执行方式也决定工具接口、权限检查、结果预算和引用生命周期。

## 决定

通过独立的 `codex-relay-standalone-search` Profile 选择客户端执行的原生 `web.run`。Profile 保留 relay 协议行为与生图声明，搜索命令由应用工具循环发送至同一 provider 的 `alpha/search`。现有 Profile 保持各自契约。

模型使用固定版本的官方命令 schema。内部工具名 `web_run` 与 wire 的 `web.run` 在协议边界映射，原生条目原样保存。函数结果保存预算内的明文检索材料；来源元数据按白名单保留，密文和未知字段只进入受控原始 HTTP Trace。

## 方案与理由

客户端执行使检索材料能够进入现有函数工具记录、敏感过滤和纪元冻结。服务端响应 ID 续接需要额外的状态链、过期和删除语义，本方案继续采用 `store:false` 和本地历史。

搜索使用稳定的业务会话、owner 和 epoch 派生 ID，保留后端返回的引用和编号。历史材料可以本地恢复；后端引用的可用期由服务决定，引用失效作为操作错误返回。

## 影响

namespace schema 需要与目标模型兼容，命令数组在应用内递归校验。HTTP 200 中的操作错误与无图片的截图结果均不能记为完整成功。新 Profile 需要对搜索、页内定位、链接、专业查询和媒体逐项实测后再用于替换已有配置。

工具结果按请求剩余预算首次裁剪并冻结。图片仅进入模型输入，沿用现有工具图片和临时保留规则；群内引用显示由独立交付投影处理。健康报告区分配置选择与实际端点验收，不自动执行计费搜索。

## 依据与相关契约

- [Codex SearchCommands](https://github.com/openai/codex/blob/77873dd0d284aeba7ce849b995b28ee8f4498d73/codex-rs/codex-api/src/search.rs)
- [Codex 搜索执行器](https://github.com/openai/codex/blob/77873dd0d284aeba7ce849b995b28ee8f4498d73/codex-rs/ext/web-search/src/tool.rs)
- [LLM 模块](../llm-module.md)、[原生回放资格](0013-native-replay-compatibility.md)、[纪元冻结](0003-epoch-history-freezing.md)、[引用显示投影](0030-citation-display-projection.md)
