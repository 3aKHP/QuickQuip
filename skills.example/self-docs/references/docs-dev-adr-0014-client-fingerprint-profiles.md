<!-- Generated from docs/dev/adr/0014-client-fingerprint-profiles.md; do not edit -->

---
status: Accepted
superseded_by: []
---

# ADR-0014：以客户端 Profile 组织出口请求特征

- 记录日期：2026-10-23
- 原始决策日期：2026-10-13

## 背景

渠道接入需要维护 UA、客户端身份头、会话编码及请求体布局。单独覆盖一个 Header 无法表达这些关联规则，分散在各协议中的静态值也难以按目标客户端版本校准。

项目同时需要兼容客户端模板和自有品牌模板，并保持业务身份与协议能力的独立职责。

## 决定

渠道选择客户端 Profile，由可编辑 TOML 及关联策略组织出口特征。模板承载版本基线、静态字段与具名绑定；代码维护加载校验、身份投影及协议组装算法。

同一业务执行使用冻结配置和模板快照，工具续轮与重试显式复用请求身份。业务 Session、上下文纪元、真实鉴权和协议能力分别维护；Profile 消费这些输入并完成相应出口投影。

## 方案与理由

既有 UA、附加 Header 和请求体覆盖继续服务于允许的自定义场景。完整模板将需要协同的字段放到同一版本基线下，并对受管字段冲突执行校验，减少手工配置产生的矛盾。

维护者选择按渠道配置 Profile，兼容模板按协议演进，自有品牌模板显式启用。各协议分阶段实现，使模板证据、序列化与真实请求可以分别复核。

## 影响

模板和算法分别维护，部署者可以查看并覆盖模板内容；新增模板需要说明支持协议、版本依据、动态绑定及可覆盖字段。

渠道选择随配置发布生效；本地模板文件由进程加载，文件修改后按当前契约重启。重试保持当前快照，后续执行使用后续加载的内容。具体默认映射和客户端版本由 Profile 契约维护。

## 依据与相关契约

- [PR #290：Profile 基础与自有品牌](https://github.com/3aKHP/QuickQuip/pull/290)
- [请求指纹 Profile 契约](../../admin/client-fingerprints.md)
- [模板目录与校验](../../../src/quickquip/llm/client_fingerprints/catalog.py)、[请求投影](../../../src/quickquip/llm/client_fingerprints/assembly.py)
- [业务 Session 身份](0002-business-session-identity.md)、[配置快照发布](0001-config-snapshot-publication.md)
