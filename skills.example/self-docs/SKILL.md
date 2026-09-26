---
name: self-docs
description: QuickQuip 官方、与部署版本对齐的公开文档副本：群聊/私聊命令与游戏玩法、部署安装、配置参考、运维排查、报错处理、开发约定、项目治理与协作约定。当用户问机器人怎么用、有哪些命令、游戏怎么玩、如何部署或配置、某个配置项或报错是什么意思，或问起行为准则、提 issue/PR、评审流程等协作问题时使用。回答 QuickQuip 相关事实时优先以本 Skill 文档为准，不要依赖训练知识。
---

# QuickQuip 文档问答

你正在基于 QuickQuip 内置的公开文档副本，回答关于本机器人的用法、配置与实现问题。

## 工作流程

1. 用用户的语言回答（默认中文）。
2. 判断问题类型：命令用法、游戏玩法、部署安装、配置项、报错排查、功能行为、开发或架构约定、项目治理与协作约定。
3. 先查下方路由表，定位最小的一篇 reference，用 `read_skill_resource`（`skill="self-docs"`）直接阅读。
4. 路由表定不了，或问题是关键词型（命令名、配置键、报错原文、精确术语）时，先用 `search_skill_resources`（`skill="self-docs"`；默认字面量、大小写不敏感，`is_regex=true` 时按正则）检索，命中给出 `file:line` 与前后各 1 行上下文，再用 `read_skill_resource` 读最小相关段落。
5. 大型 reference（如 `references/root-changelog.md`）单次读不完：读取有字节上限（默认 64KiB，超限只返回前段），按 search 命中的行号用 `read_skill_resource` 的 `start_line`/`end_line` 读对应行段。
6. `references/index.md` 是全部页面的标题与关键词总表；路由表和检索都不确定时读它挑页。
7. 区分成文的当前行为与建议。不要编造命令、配置键、默认值、文件位置或版本状态。
8. 不要声称查看过该群的实际配置、数据或运行日志，除非对话中已经给出这些事实。
9. 来源冲突时以公开权威为准：用户语义以 `docs-user-*` 页面为准，配置形态以 `references/docs-admin-configuration.md` 为准，实现约定以 `docs-dev-*` 页面为准。
10. 引用答案来源的公开文档路径（每篇 reference 头部的 `Generated from` 标记即源路径，如 `docs/user/group-commands.md`）；不要暴露宿主机的绝对路径。
11. 文档没覆盖的问题，如实说明文档缺失，建议就近的排查面（群管理员、部署日志、`/skill list`）；不要凭训练记忆补洞。
12. 不要因为是文档 Skill 就执行脚本、修改配置，或把文档指引当作对用户的授权承诺。

## 路由表

| 主题 | Reference |
|------|-----------|
| 项目概览、功能简介、快速安装 | `references/root-readme.md` |
| 版本变更、某版本新行为、升级说明 | `references/root-changelog.md` |
| 路线图、计划中的功能 | `references/root-roadmap.md` |
| 贡献流程、提交规范 | `references/root-contributing.md` |
| 安全策略、漏洞报告 | `references/root-security.md` |
| 行为准则、项目价值观（彩蛋 RFC） | `references/root-code_of_conduct.md` |
| AI 协作约定、协作者说明 | `references/root-claude.md` |
| 公开文档总导航 | `references/docs-index.md` |
| 群聊命令（触发 AI、语录、留言、管理员命令等） | `references/docs-user-group-commands.md` |
| 群内游戏玩法（金币经济等） | `references/docs-user-group-games.md` |
| AI 工具发现（用户视角） | `references/docs-user-llm-tool-discovery.md` |
| 私聊命令、私聊与群聊区别 | `references/docs-user-private-commands.md` |
| 新三国梗触发 | `references/docs-user-three-kingdoms-memes.md` |
| 云端部署、安装、启动、升级 | `references/docs-admin-deployment.md` |
| 配置项参考（.env 与各 TOML） | `references/docs-admin-configuration.md` |
| 游戏系统管理与配置 | `references/docs-admin-game-config.md` |
| OneBot 适配器状态与选择 | `references/docs-admin-onebot-adapters.md` |
| NapCat → LLBot 迁移 | `references/docs-admin-migration-napcat-to-llbot.md` |
| 记录身份迁移与验收 | `references/docs-admin-record-identities.md` |
| 敏感词过滤器 | `references/docs-admin-sensitive-filter.md` |
| Skill 系统部署与安全模型 | `references/docs-admin-skills.md` |
| LLM 工具发现配置 | `references/docs-admin-tool-discovery.md` |
| Web Admin 管理后台 | `references/docs-admin-web-admin.md` |
| 项目架构与结构 | `references/docs-dev-architecture.md` |
| LLM 模块实现说明 | `references/docs-dev-llm-module.md` |
| 开发者文档索引 | `references/docs-dev-readme.md` |
| 开发工作流、分支与发布 | `references/docs-dev-branching.md` |
| 代码规范与架构原则 | `references/docs-dev-style.md` |
| 测试纪律、反模式与删留依据 | `references/docs-dev-testing.md` |
| 版本号约定 | `references/docs-dev-versioning.md` |
| 游戏框架开发 | `references/docs-dev-game-framework.md` |
| MCP 集成 | `references/docs-dev-mcp-integration.md` |
| 记录正文与成员身份契约 | `references/docs-dev-record-identities.md` |
| 正则表达式教程 | `references/docs-dev-regex-tutorial.md` |
| STS 公式化回复模块 | `references/docs-dev-sts-formula.md` |
| 工具发现实现说明 | `references/docs-dev-tool-discovery.md` |
| CR 评审流程、独立评审 agent 约定 | `references/claude-agents-quickquip-cr-reviewer.md` |
| 提 Issue（备忘/Memo 模板） | `references/github-issue_template-memo.md` |
| 提 PR 怎么写（通用模板、变更分级） | `references/github-pull_request_template.md` |
| 发布 PR 模板（dev → main） | `references/github-pull_request_template-release.md` |
| 生产运维脚本、部署事务细节 | `references/prod.example-readme.md` |
| 全部页面索引（标题 + 关键词） | `references/index.md` |
