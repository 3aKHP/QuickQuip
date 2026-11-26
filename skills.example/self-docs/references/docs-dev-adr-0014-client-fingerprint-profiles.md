<!-- Generated from docs/dev/adr/0014-client-fingerprint-profiles.md; do not edit -->

---
status: Accepted
superseded_by: []
---

# ADR-0014：以客户端 Profile 组织出口请求特征

- 记录日期：2026-10-23
- 原始决策日期：2026-10-13

## 背景

不同上游渠道与中转网关往往对 `User-Agent`、客户端身份标识头、会话 ID 编码方式以及请求体字段排布存在成套预期。仅靠零散的自定义 Header 覆盖难以表达多字段之间的联动关系，把默认请求头硬编码分散在各协议适配器中也不便于按目标客户端版本统一核对和升级。

系统需要一套既能复刻特定官方客户端出口特征、又能清晰表达 QuickQuip 自有品牌标识的配置抽象，同时不侵入上层业务会话与鉴权凭据的职责。

## 决定

在渠道配置上引入客户端请求指纹 Profile，通过可编辑的 TOML 模板文件与代码侧组装策略协同生成出口请求特征：

- **模板与代码分工**：TOML 模板声明目标客户端版本基线、静态请求头／请求体字段及具名动态绑定槽位；代码层负责模板加载校验、从业务上下文派生投影身份以及各协议的最终报文拼装。
- **执行期快照隔离**：单次业务执行固定其启动时的渠道配置与 Profile 模板快照，同一任务内的工具续轮和 HTTP 重试显式复用同一组派生请求身份。Profile 仅作为出口投影层消费业务 Session（[ADR-0002](0002-business-session-identity.md)）、会话纪元、已展开鉴权凭据与协议能力参数，不接管会话生命周期或鉴权存储。

## 方案与理由

渠道原有的自定义 `User-Agent`、附加 Header 与额外请求体字段继续服务于轻量微调；在此之上引入完整 Profile 模板，可以把必须配套出现的客户端版本头、平台属性与会话标识归拢到同一份版本基线下，并在加载阶段拦截受管字段冲突，减少人工拼凑参数引发的特征自相矛盾。

按渠道粒度绑定 Profile 并按协议分批落地，便于逐项核对公开客户端报文证据、序列化顺序与真实上游兼容性；兼容型模板可随上游客户端版本演进更新，自有品牌模板则由管理员显式选用。

## 影响

部署者可以直接审阅或在本地目录定制 Profile 模板；新增内置模板时需同步记录其支持的协议范围、客户端版本依据、动态绑定槽位及允许渠道覆盖的字段。

渠道绑定的 Profile 名称随 LLM 配置发布即时切换；磁盘上的本地 TOML 模板文件在进程启动时加载，手工修改模板内容后需重启服务生效。在途重试继续使用任务开始时固定的模板快照，新任务则读取最新加载的快照。

## 依据与相关契约

- [PR #290：Profile 基础与自有品牌](https://github.com/3aKHP/QuickQuip/pull/290)
- [请求指纹管理手册](../../admin/client-fingerprints.md)、[请求指纹开发契约](../client-fingerprints.md)
- [模板目录与校验](../../../src/quickquip/llm/client_fingerprints/catalog.py)、[请求投影组装](../../../src/quickquip/llm/client_fingerprints/assembly.py)
- [业务 Session 身份](0002-business-session-identity.md)、[配置快照发布](0001-config-snapshot-publication.md)
