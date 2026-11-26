---
status: Accepted
superseded_by: []
---

# ADR-0031：由客户端执行搜索并保存可回放材料

- 记录日期：2026-11-17
- 原始决策日期：2026-11-17

## 背景

在采用 `store: false` 无状态请求模式的 OpenAI Responses 渠道中，服务端托管搜索（hosted `web_search`）返回的响应通常只包含搜索调用条目与最终回答里的来源 URL 列表，不包含被检索网页的摘要或正文片段。一旦用户在后续轮次针对方才搜到的网页细节继续追问，模型在本地重放历史时便因缺少原始检索材料而无法核实细节或被迫重复搜索。此外，搜索究竟由上游服务端黑盒执行还是由本地应用循环接管，也直接决定了工具权限门控、结果上下文预算、敏感词过滤与来源引用的生命周期。

## 决定

新增独立的 `codex-relay-standalone-search` 协议能力 Profile，支持由 QuickQuip 客户端工具循环接管原生 `web.run` 搜索命令并将检索材料纳入本地可回放历史：

- **独立能力 Profile 与端点路由**：选用 `codex-relay-standalone-search` 时，请求继续保留中转兼容协议结构与原生生图能力声明，同时向模型暴露固定版本的官方 `web.run` 命令 schema；模型发出搜索工具调用后，由本地工具循环将搜索命令转发至同一渠道下的 `alpha/search` 搜索端点执行。
- **协议名映射与白名单持久化**：内部工具注册名 `web_run` 与协议报文中的 `web.run` 在适配器边界双向映射，模型生成的原生调用条目按原样保存以维持同源回放兼容。搜索返回的正文材料经请求预算裁剪后作为标准函数工具结果落库；网页来源元数据按白名单提取保存，上游附带的加密字段或未知扩展属性仅在开启诊断时进入受控的原始 HTTP Trace，不写入业务库。

## 方案与理由

将搜索改为客户端工具循环执行后，检索到的网页摘录能够自然接入既有的函数工具记录、出入口敏感词过滤与纪元内历史冻结（[ADR-0003](0003-epoch-history-freezing.md)），跨轮追问时模型无需依赖上游有状态的 `previous_response_id` 会话链，避免了服务端状态过期、跨渠道不可迁移以及删除同步等额外复杂度。

搜索请求使用由业务 Session、归属标识（Owner）与当前纪元稳定派生的上下文标识，并保留搜索后端返回的引用编号：跨轮对话可随时从本地已冻结的工具结果中重读网页材料；若模型在同一纪元内尝试继续打开或定位某个旧引用而后端缓存已过期，则将该失效结果作为明确的工具操作错误返回给模型处理。

## 影响

上游模型必须支持对应的 namespace 工具 schema，客户端在转发执行前需对模型提交的批量搜索命令数组做递归参数校验；对于 HTTP 状态码为 200 但内部携带搜索操作错误、或请求网页截图却未返回有效图片数据的响应，均须如实记为部分失败或操作错误，不得标记为完整成功。将既有渠道切换到该 Profile 前，需在目标中转端点上逐项实测关键词搜索、页内定位、指定链接打开、垂直领域查询及媒体返回兼容性。

单次搜索结果在首次进入历史时按当轮剩余预算完成裁剪并随纪元冻结；网页附图仅作为当轮多模态输入送入模型，遵循既有的工具图片临时保留边界，聊天窗口内的引用链接净化则统一交由交付显示投影（[ADR-0030](0030-citation-display-projection.md)）处理。后台健康报告明确区分“渠道配置已选用该 Profile”与“搜索端点实测可用”，常规探活不会自动发起产生计费的真实搜索请求。

## 依据与相关契约

- [PR #359：Responses 客户端独立搜索](https://github.com/3aKHP/QuickQuip/pull/359)
- [Codex SearchCommands 定义](https://github.com/openai/codex/blob/77873dd0d284aeba7ce849b995b28ee8f4498d73/codex-rs/codex-api/src/search.rs)、[Codex 搜索执行器参考](https://github.com/openai/codex/blob/77873dd0d284aeba7ce849b995b28ee8f4498d73/codex-rs/ext/web-search/src/tool.rs)
- [LLM 模块说明](../llm-module.md#75-联网搜索)
- [原生回放资格](0013-native-replay-compatibility.md)、[纪元冻结](0003-epoch-history-freezing.md)、[来源引用显示投影](0030-citation-display-projection.md)
