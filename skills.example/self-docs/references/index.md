<!-- Generated index; do not edit. Run: python scripts/ci/sync_self_docs_references.py -->

# QuickQuip 文档索引

与部署版本对齐的公开文档快照，是 self-docs Skill 的路由总表与检索兜底索引。

## 路由指引

- 群友命令、玩法、梗触发 → 用户文档（`docs-user-*`）。
- 部署、配置、运维、报错排查 → 管理文档（`docs-admin-*`）。
- 架构、模块契约、开发约定 → 开发文档（`docs-dev-*`）。
- 项目概念与名称 → 术语表（`docs-glossary.md`）；设计理由与取舍 → ADR。
- ADR 按状态与替代关系阅读；Accepted 表示方案获接受，当前实现与操作以相应现行契约为准。
- 项目概览与安装 → `root-readme.md`；版本行为变更 → `root-changelog.md`；计划功能 → `root-roadmap.md`。
- 每条列出该页标题与关键词；`search_skill_resources` 未命中时按关键词挑页，用 `read_skill_resource` 阅读。
- 文档未覆盖的问题如实说明缺失，不要凭训练记忆编造。

## Root 文档

- `CHANGELOG.md` → `references/root-changelog.md` — Changelog ｜ 关键词：migration_required、.env、config/managed/config.db、data/config_runtime.db、；Windows 使用包内、，完成迁移后再运行、。云端 deploy-v4 使用、-MigrateStorage、.runtime.db、unpack
- `CLAUDE.md` → `references/root-claude.md` — CLAUDE.md — AI 协作者说明 ｜ 关键词：docs/dev/documenting.md、docs/dev/、docs/admin/、docs/user/、prod.example/、scripts/deploy/、scripts/ops/、prod/、.venv、uv venv
- `CODE_OF_CONDUCT.md` → `references/root-code_of_conduct.md` — RFC 325799 — QuickQuip Code of Conduct ｜ 关键词：∀t: Reading(t) → Reading(t)、submit(x) → (User(x) ↔ User(x))、|P| ∈ {0, 1} → ∀p ∈ P: Civil(p, air)、Comply(x) → ¬Violate(x)、Disagree(x) → (C ≡ C)、P(reply) + P(¬reply) = 1
- `CONTRIBUTING.md` → `references/root-contributing.md` — Contributing to QuickQuip ｜ 关键词：docs/dev/README.md、docs/dev/branching.md、style.md、testing.md、documenting.md、src/、python、CLAUDE.md、CLAUDE.local.md、scripts/git-hooks/pre-push
- `README.md` → `references/root-readme.md` — QuickQuip — QQ 群聊妙语机器人 ｜ 关键词：regex_context、llm_context、config/games.toml、/roll、/choose、/fortune、/vote、/quote、/find、/tell
- `ROADMAP.md` → `references/root-roadmap.md` — ROADMAP ｜ 关键词：docs/、/llm reload、awakening、chat_rules、generation、games、niuniu_text*、/llm probe、context_limit、builtin_search
- `SECURITY.md` → `references/root-security.md` — 安全策略 / Security Policy ｜ 关键词：dev、-dev.N、-rc.N、cccp1945@vip.qq.com、[QuickQuip security]

## 文档导航

- `docs/index.md` → `references/docs-index.md` — QuickQuip 文档导航 ｜ 关键词：/skill list、.env、generation.toml、awakening.toml、chat_rules.toml、games.toml、sensitive_words.toml、personas/、tool_search、tool_list

## 项目术语

- `docs/glossary.md` → `references/docs-glossary.md` — QuickQuip 项目术语表 ｜ 关键词：provider_id、model、(provider_id, model)、.config-workspace/、unpack、refresh、pack、.config-staging/、push、pull

## 用户文档（群友）

- `docs/user/group-commands.md` → `references/docs-user-group-commands.md` — QuickQuip 群内指令速查 ｜ 关键词：/ai 你的问题、/search 关键词、/roll 2d6、/ai、/ai 你觉得今天适合熬夜吗、@机器人 这句话是什么意思、/search news 关键词、/search finance 关键词、/search news OpenAI 最新模型、/defectify
- `docs/user/group-games.md` → `references/docs-user-group-games.md` — QuickQuip 群内游戏指南 ｜ 关键词：config/games.toml、/game start 数字炸弹、/game start 21点 200、/game start 俄罗斯轮盘 200、/注册牛牛、/签到、/金币、/金币排行、/game list、/game stop
- `docs/user/llm-skills.md` → `references/docs-user-llm-skills.md` — AI Skill 扩展能力说明 ｜ 关键词：/ai、/skill list、/ai 你的 /quote 命令怎么用？、/ai 你支持什么配置？、/ai 这个报错是什么意思？、/ai 服务器现在负载高吗？、/ai 内存还剩多少？磁盘快满了吗？、/ai 机器人怎么有点卡，是不是内存不足？
- `docs/user/llm-tool-discovery.md` → `references/docs-user-llm-tool-discovery.md` — AI 工具发现说明 ｜ 关键词：/ai 搜一下 Python 3.13 的官方发布公告、/ai 查查群里有没有关于阿桃喜欢什么的记忆、/ai 用 GitHub 工具列出 3aKHP/QuickQuip 当前仍开放的 issue
- `docs/user/private-commands.md` → `references/docs-user-private-commands.md` — QuickQuip 私聊指令速查 ｜ 关键词：/ai、/start_session、/end_session、/resume_session、<尖括号>、[方括号]、/resume_session [N]、/sessions、/delete_session N、/start_session --preset "请用英文回复"
- `docs/user/three-kingdoms-memes.md` → `references/docs-user-three-kingdoms-memes.md` — 新三国梗触发指南

## 管理文档（部署与运维）

- `docs/admin/client-fingerprints.md` → `references/docs-admin-client-fingerprints.md` — 请求指纹 Profile ｜ 关键词：client_fingerprint、default、opencode2、codex、claude-code、gemini-cli、quickquip、system、legacy-gemini、?key=
- `docs/admin/config-sync.md` → `references/docs-admin-config-sync.md` — 用 qqsync 同步和部署配置 ｜ 关键词：qqsync、qqsync refresh、qqsync push、qqsync pull、qqconf、.env、qqconf unpack、qqconf pack、QUICKQUIP_DEPLOY_LOCATION、local
- `docs/admin/config-workspace.md` → `references/docs-admin-config-workspace.md` — 用 qqconf 编辑本地配置 ｜ 关键词：config/managed/config.db、.env、qqconf、.config-workspace/、unpack、refresh、pack、python -m quickquip.config_workspace、--root /path/to/QuickQuip、--workspace /path/to/workspace
- `docs/admin/configuration.md` → `references/docs-admin-configuration.md` — QuickQuip 配置参考 ｜ 关键词：.env、config/managed/config.db、qqconf pack、local、cloud、qqsync push、generation.toml、awakening.toml、chat_rules.toml、DRIVER
- `docs/admin/deployment.md` → `references/docs-admin-deployment.md` — QuickQuip 云端 Docker 部署指南 ｜ 关键词：deploy-v4、local、cloud、source、docker、prod.example/、prod/、scripts/deploy/、scripts/ops/、.env
- `docs/admin/game-config.md` → `references/docs-admin-game-config.md` — 游戏系统管理 ｜ 关键词：config/games.toml、/game list、/game stop、/rules、/disable <rule_name>、/enable <rule_name>、config/games.toml.example、[economy]、sign_base_gold、10
- `docs/admin/global-admins.md` → `references/docs-admin-global-admins.md` — 全局管理员 ｜ 关键词：config/admins.toml、config/admins.toml.example、ADMIN_TRACE、registry_loaded、global_admin_unlock、SUPERUSERS
- `docs/admin/installation.md` → `references/docs-admin-installation.md` — 安装与部署方式 ｜ 关键词：.env、start.bat、ONEBOT_WS_URLS、3001、ONEBOT_ACCESS_TOKEN、http://127.0.0.1:5104/ops/、WEB_ADMIN_PASSWORD、deploy-v4、Copy-Item .env.example .env、QQ_ACCOUNT
- `docs/admin/llm-configuration.md` → `references/docs-admin-llm-configuration.md` — LLM 配置数据库操作指南 ｜ 关键词：config/managed/config.db、config/llm.json.example、/ops/api/llm-configuration/metadata、config/personas.example/、config/personas/、quickquip-default、.env、up -d、my-provider、OPENAI_API_KEY
- `docs/admin/mcp-servers.md` → `references/docs-admin-mcp-servers.md` — MCP Server 接入指南 ｜ 关键词：py、echo_server.py、Uvicorn running on http://127.0.0.1:8017、http://127.0.0.1:8017/mcp、legacy、2025-03-26、127.0.0.1、host.docker.internal、echo_lab、http
- `docs/admin/memory.md` → `references/docs-admin-memory.md` — 管理长期记忆 ｜ 关键词：/llm memory on、list_memories、read_memory、write_memory、delete_memory、/remember 正文、/remember --id 42 新正文、/memories [关键词]、/memories --page 2 [关键词]、/memories --id 42
- `docs/admin/migration-napcat-to-llbot.md` → `references/docs-admin-migration-napcat-to-llbot.md` — NapCat → LLBot 迁移指南 ｜ 关键词：mlikiowa/napcat-docker、initialencounter/llonebot:v7.12.14-7.3.2-45758、docker-compose.example.yml、docker-compose.yml、.env、entrypoint、/bin/sh -c、user@server、http://127.0.0.1:3080、ws-reverse
- `docs/admin/onebot-adapters.md` → `references/docs-admin-onebot-adapters.md` — OneBot 适配器状态与选择 ｜ 关键词：.env、ONEBOT_WS_URLS、DRIVER、~websockets、~fastapi、ws://<bot 地址>:8080/onebot/v11/ws、ONEBOT_ACCESS_TOKEN、message.group、sender.card、nickname
- `docs/admin/record-identities.md` → `references/docs-admin-record-identities.md` — 记录身份迁移与验收 ｜ 关键词：requirements.txt、--preview-limit 0、--apply、--database、memories、quotes、offline_messages、all、data/llm.db、data/quotes.db
- `docs/admin/sensitive-filter.md` → `references/docs-admin-sensitive-filter.md` — 敏感词过滤部署与维护 ｜ 关键词：config/sensitive_words.toml、words、block、soft、/llm reload、/llm health verbose、sensitive_filter、GET /ops/api/sensitive-filter/status、[内容已屏蔽]、/draw
- `docs/admin/skills.md` → `references/docs-admin-skills.md` — Skill 系统（`skills/`） ｜ 关键词：skills/、description、SKILL.md、references/、scripts/、.py、.sh、self-docs、host-healthcheck、settings.skills.catalog_dir
- `docs/admin/storage-migration.md` → `references/docs-admin-storage-migration.md` — 将配置与运行数据分开存储（存储迁移指南） ｜ 关键词：data/llm_config.db、migration_required、init、start.bat、config/managed/config.db、data/config_runtime.db、config/managed/scheduled_messages.json、data/pending_scheduled_messages.json、data/、data/llm.db
- `docs/admin/tool-discovery.md` → `references/docs-admin-tool-discovery.md` — LLM 工具发现配置 ｜ 关键词：tool_search、settings.tools、enabled、enabled_mode = "replace"、discovery_mode、off、on、auto、discovery_min_tools、discovery_search_limit
- `docs/admin/web-admin.md` → `references/docs-admin-web-admin.md` — Web Admin 管理后台 ｜ 关键词：/ops/、.env、WEB_ADMIN_PASSWORD、start.bat、http://127.0.0.1:5104/ops/、ssh -N -L 5104:127.0.0.1:5104 user@server、web-admin、up -d、/ops/#/stats、awakening_*

## 开发文档

- `docs/dev/architecture.md` → `references/docs-dev-architecture.md` — QuickQuip 项目架构与结构 ｜ 关键词：README.md、style.md、pip install -e .、python bot.py、.env、prod/、src/quickquip/、chat、common、llm
- `docs/dev/branching.md` → `references/docs-dev-branching.md` — QuickQuip 开发工作流与发布流程 ｜ 关键词：dev、main、style.md、testing.md、documenting.md、architecture.md、versioning.md、feat、fix、refactor
- `docs/dev/client-fingerprints.md` → `references/docs-dev-client-fingerprints.md` — 请求指纹与协议转换实现 ｜ 关键词：src/quickquip/llm/client_fingerprints/、defaults/、data/client_identity.json、data/、quickquip、X-Stainless-*、claude-code、opencode2、codex、gemini-cli
- `docs/dev/config-workspace.md` → `references/docs-dev-config-workspace.md` — qqconf 本地配置工作副本契约 ｜ 关键词：quickquip.config_workspace、qqconf unpack|refresh|pack、db/、configuration.inventory、config_workspace.layout、quickquip.configuration、.qqconf/state.json、None、__quickquip_value__、null
- `docs/dev/configuration-storage.md` → `references/docs-dev-configuration-storage.md` — 配置与运行存储 ｜ 关键词：config/managed/config.db、scope_settings、niuniu_group_text、config/managed/scheduled_messages.json、data/config_runtime.db、data/llm.db、agent_scopes.private_chat_active、data/niuniu.db、data/pending_scheduled_messages.json、ConfigService
- `docs/dev/documenting.md` → `references/docs-dev-documenting.md` — QuickQuip 公开文档规范 ｜ 关键词：docs/、README.md、docs/glossary.md、docs/user/、docs/admin/、docs/dev/、docs/dev/adr/、CHANGELOG.md、ROADMAP.md、../index.md
- `docs/dev/game-framework.md` → `references/docs-dev-game-framework.md` — 游戏框架开发者指南 ｜ 关键词：BaseGame、aliases、src/quickquip/app/message_pipeline.py、GameResult、finished、group_id、OrderedDict[str, Session]、src/quickquip/adapters/nonebot/commands.py、command_parts/、_ensure_schema()
- `docs/dev/llm-configuration-api.md` → `references/docs-dev-llm-configuration-api.md` — LLM 配置后端接口 ｜ 关键词：config/managed/config.db、data/config_runtime.db、/ops/api/llm-configuration、quickquip_admin_session、Origin、Referer、在进程内构造应用导出，随约束或路由变更同步提交；运行中的管理 API 不提供、/redoc、/openapi.json、format_version
- `docs/dev/llm-configuration-frontend.md` → `references/docs-dev-llm-configuration-frontend.md` — LLM 配置管理前端交付契约 ｜ 关键词：/ops/#/llm-config、draft_revision、published_revision、loaded_revision、draft_version、published_version、loaded_version、{saved_at, note}、PUT /note、202
- `docs/dev/llm-module.md` → `references/docs-dev-llm-module.md` — QuickQuip LLM 模块说明 ｜ 关键词：/search、LLM_TRACE_FLAG_FILE、data/llm_trace.db、run_tool_call_loop、LLM_TRACE_MEDIA_MIN_BYTES、b64_json、partial_image_b64、data、data/trace_blobs/、[qq:blob sha256=<hex> bytes=<n>]
- `docs/dev/mcp-integration.md` → `references/docs-dev-mcp-integration.md` — QuickQuip MCP 集成说明 ｜ 关键词：ToolRegistry、config/managed/config.db、settings.mcp、config.toml、search_web、tavily_search、tavily_crawl、tavily_research、docker、/var/run/docker.sock
- `docs/dev/mcp-tutorial.md` → `references/docs-dev-mcp-tutorial.md` — 从零理解 MCP —— 以 QuickQuip 项目为例 ｜ 关键词：settings.mcp.servers、llm-module.md、src/quickquip/llm/mcp/、src/quickquip/llm/config_document.py、src/quickquip/llm/service_parts/mcp_lifecycle.py、。配置权威模板为、MCPClient、mcp/client.py、ToolRegistry、mcp_*
- `docs/dev/README.md` → `references/docs-dev-readme.md` — QuickQuip 开发者文档 ｜ 关键词：docs/dev/、../glossary.md、adr/README.md、documenting.md、architecture.md、style.md、testing.md、branching.md、versioning.md、record-identities.md
- `docs/dev/record-identities.md` → `references/docs-dev-record-identities.md` — 记录正文与成员身份契约 ｜ 关键词：private:<QQ>、common/identity.py、common/identity_sources.py、app/identities.py、llm/identity.py、LLMService.group_identities()、/llm reload、data/stats.json、common/record_content.py、common/record_search.py
- `docs/dev/regex-tutorial.md` → `references/docs-dev-regex-tutorial.md` — 从零开始学习正则表达式 —— 以 QuickQuip 项目为例 ｜ 关键词：config/chat_rules.toml、config/chat_rules.toml.example、src/quickquip/chat/text_rules.py、re、python3 --version、py --version、.\python\python.exe --version、regex_practice.py、.py、.py.txt
- `docs/dev/skill-tutorial.md` → `references/docs-dev-skill-tutorial.md` — 从零开始编写 Skill —— 以 QuickQuip 项目为例 ｜ 关键词：skills/、skills.example/self-docs、skills.example/host-healthcheck、SKILL.md、name + description、activate_skill、references/、<skill_catalog>、name、read_skill_resource
- `docs/dev/sts-formula.md` → `references/docs-dev-sts-formula.md` — STS 公式化回复模块 ｜ 关键词：quickquip.sts、formulas/card_le/、formulas/defectify/、/defectify、nkhoit/spire-archive、scripts/maintenance/refresh_sts_lexicon.py、src/quickquip/sts/sts_lexicon.json、14e05c09dc38、；先核对要采用的上游提交，并更新脚本的、和
- `docs/dev/style.md` → `references/docs-dev-style.md` — QuickQuip 代码规范与架构原则 ｜ 关键词：architecture.md、branching.md、documenting.md、line-length = 100、E + F、any、data/、.env、prod/、utils.py
- `docs/dev/testing.md` → `references/docs-dev-testing.md` — QuickQuip 测试纪律 ｜ 关键词：style.md、CONTRIBUTING.md、branching.md、in、len(MCP_FAILURE_KINDS) == 8、isinstance(result, str)、sleep、try、assert False、except Exception
- `docs/dev/tool-discovery.md` → `references/docs-dev-tool-discovery.md` — LLM 工具发现实现说明 ｜ 关键词：tool_search、tool_list、LLMRequest.tools、src/quickquip/llm/tools.py、ToolManifestEntry、src/quickquip/llm/tool_registry.py、src/quickquip/llm/service_parts/tools.py、src/quickquip/llm/tool_discovery.py、loaded_names、src/quickquip/llm/tool_loop.py
- `docs/dev/versioning.md` → `references/docs-dev-versioning.md` — QuickQuip 版本号约定 ｜ 关键词：Major.Minor.Patch、branching.md、pyproject.toml、version、frontend/package.json、1.15.1-dev.0、1.15.1-dev.1、1.15.1-rc.1、1.15.1、1.16.0-dev.0
- `docs/dev/web-admin.md` → `references/docs-dev-web-admin.md` — Web Admin 会话与执行机制 ｜ 关键词：auth_basic、429、/ops/、GET /ops/api/auth/me、WEB_ADMIN_PASSWORD、POST /ops/api/auth/login、Set-Cookie、/ops/api/*、POST /ops/api/auth/logout、data/web_admin_sessions.db

## 架构决策记录（含历史）

- `docs/dev/adr/0001-config-snapshot-publication.md` → `references/docs-dev-adr-0001-config-snapshot-publication.md` — ADR-0001：通过不可变快照发布配置 ｜ 状态：Superseded ｜ 替代记录：[0023-online-and-offline-configuration-publication.md](docs-dev-adr-0023-online-and-offline-configuration-publication.md) ｜ 关键词：.env
- `docs/dev/adr/0002-business-session-identity.md` → `references/docs-dev-adr-0002-business-session-identity.md` — ADR-0002：由业务维护 Session 身份 ｜ 状态：Accepted
- `docs/dev/adr/0003-epoch-history-freezing.md` → `references/docs-dev-adr-0003-epoch-history-freezing.md` — ADR-0003：在纪元内冻结历史表达 ｜ 状态：Accepted
- `docs/dev/adr/0004-agent-execution-replay-delivery.md` → `references/docs-dev-adr-0004-agent-execution-replay-delivery.md` — ADR-0004：分离执行记录、历史投影与消息交付 ｜ 状态：Accepted
- `docs/dev/adr/0005-tool-result-retention.md` → `references/docs-dev-adr-0005-tool-result-retention.md` — ADR-0005：区分临时查询结果与可保留工具事实 ｜ 状态：Accepted ｜ 关键词：bounded、ephemeral、7a11405、EPHEMERAL、BOUNDED、retention
- `docs/dev/adr/0006-layered-architecture-composition.md` → `references/docs-dev-adr-0006-layered-architecture-composition.md` — ADR-0006：按领域分层并由应用层装配 ｜ 状态：Accepted
- `docs/dev/adr/0007-unified-chat-archive.md` → `references/docs-dev-adr-0007-unified-chat-archive.md` — ADR-0007：统一群聊归档并按消费方序列化 ｜ 状态：Accepted
- `docs/dev/adr/0008-record-content-member-identity.md` → `references/docs-dev-adr-0008-record-content-member-identity.md` — ADR-0008：分离记录正文、成员关联与展示名称 ｜ 状态：Accepted
- `docs/dev/adr/0009-web-admin-server-sessions.md` → `references/docs-dev-adr-0009-web-admin-server-sessions.md` — ADR-0009：通过服务端会话保护管理接口 ｜ 状态：Accepted
- `docs/dev/adr/0010-global-admin-registry.md` → `references/docs-dev-adr-0010-global-admin-registry.md` — ADR-0010：由项目注册表维护全局管理员 ｜ 状态：Accepted
- `docs/dev/adr/0011-transactional-deployment-recovery.md` → `references/docs-dev-adr-0011-transactional-deployment-recovery.md` — ADR-0011：以事务部署版本并保留共享运行数据 ｜ 状态：Accepted
- `docs/dev/adr/0012-static-prefix-turn-envelope.md` → `references/docs-dev-adr-0012-static-prefix-turn-envelope.md` — ADR-0012：将动态轮次信息放入当轮信封 ｜ 状态：Accepted
- `docs/dev/adr/0013-native-replay-compatibility.md` → `references/docs-dev-adr-0013-native-replay-compatibility.md` — ADR-0013：按归属与结构校验选择原生回放 ｜ 状态：Accepted
- `docs/dev/adr/0014-client-fingerprint-profiles.md` → `references/docs-dev-adr-0014-client-fingerprint-profiles.md` — ADR-0014：以客户端 Profile 组织出口请求特征 ｜ 状态：Accepted
- `docs/dev/adr/0015-progressive-skill-loading.md` → `references/docs-dev-adr-0015-progressive-skill-loading.md` — ADR-0015：通过工具调用渐进加载 Skill 内容 ｜ 状态：Accepted
- `docs/dev/adr/0016-trusted-skill-execution.md` → `references/docs-dev-adr-0016-trusted-skill-execution.md` — ADR-0016：由部署者管理受信任 Skill 并约束脚本执行 ｜ 状态：Accepted
- `docs/dev/adr/0017-preset-skill-distribution.md` → `references/docs-dev-adr-0017-preset-skill-distribution.md` — ADR-0017：保留可选 Skill 副本并显式检测和同步漂移 ｜ 状态：Accepted
- `docs/dev/adr/0018-mcp-result-normalization.md` → `references/docs-dev-adr-0018-mcp-result-normalization.md` — ADR-0018：将 MCP 结果归一化为受控内部内容 ｜ 状态：Accepted
- `docs/dev/adr/0019-configuration-three-way-sync.md` → `references/docs-dev-adr-0019-configuration-three-way-sync.md` — ADR-0019：通过共同配置基线协调双向同步 ｜ 状态：Superseded ｜ 替代记录：[0024-directional-configuration-deployment.md](docs-dev-adr-0024-directional-configuration-deployment.md) ｜ 关键词：.env
- `docs/dev/adr/0020-editable-configuration-workspaces.md` → `references/docs-dev-adr-0020-editable-configuration-workspaces.md` — ADR-0020：以持久 TOML 工作副本编辑配置包 ｜ 状态：Superseded ｜ 替代记录：[0022-local-configuration-workspace-cli.md](docs-dev-adr-0022-local-configuration-workspace-cli.md)
- `docs/dev/adr/0021-configuration-runtime-storage-separation.md` → `references/docs-dev-adr-0021-configuration-runtime-storage-separation.md` — ADR-0021：先分离配置与运行数据，再重构本地配置工具 ｜ 状态：Accepted ｜ 关键词：.env、data/llm.db、group_settings、data/niuniu.db、niuniu_group_text、data/llm_config.db、config_operations、bot_runtime、enabled、config/managed/config.db
- `docs/dev/adr/0022-local-configuration-workspace-cli.md` → `references/docs-dev-adr-0022-local-configuration-workspace-cli.md` — ADR-0022：以 qqconf 统一编辑本地持久化配置 ｜ 状态：Superseded ｜ 替代记录：[0024-directional-configuration-deployment.md](docs-dev-adr-0024-directional-configuration-deployment.md) ｜ 关键词：.env、config/、data/、qqconf、unpack、refresh、pack、.config-workspace/、db/、.config-staging/
- `docs/dev/adr/0023-online-and-offline-configuration-publication.md` → `references/docs-dev-adr-0023-online-and-offline-configuration-publication.md` — ADR-0023：通过不可变快照完成在线与停服发布 ｜ 状态：Accepted ｜ 关键词：.env
- `docs/dev/adr/0024-directional-configuration-deployment.md` → `references/docs-dev-adr-0024-directional-configuration-deployment.md` — ADR-0024：工作副本与单向配置部署 ｜ 状态：Accepted ｜ 关键词：.qqconf/、.env、QUICKQUIP_DEPLOY_LOCATION=local|cloud、QUICKQUIP_DEPLOY_RUNTIME=source|docker、.config-staging/、refresh、push、pull
- `docs/dev/adr/0025-tracked-operations-programs.md` → `references/docs-dev-adr-0025-tracked-operations-programs.md` — ADR-0025：统一分发运维程序并分离生产配置 ｜ 状态：Accepted ｜ 关键词：scripts/deploy/、server/、legacy/、scripts/ops/、scripts/maintenance/、prod.example/、prod/、prod/hooks/deployment.sh、docker/Dockerfile.prod、.env
- `docs/dev/adr/0026-conversation-owned-memory.md` → `references/docs-dev-adr-0026-conversation-owned-memory.md` — ADR-0026：由主对话模型维护会话记忆 ｜ 状态：Accepted
- `docs/dev/adr/README.md` → `references/docs-dev-adr-readme.md` — 架构决策记录 ｜ 关键词：NNNN-short-title.md、Proposed、Accepted、Rejected、Superseded、status、superseded_by
- `docs/dev/adr/template.md` → `references/docs-dev-adr-template.md` — ADR 模板 ｜ 关键词：NNNN-short-title.md

## 其他

- `.claude/agents/quickquip-cr-reviewer.md` → `references/claude-agents-quickquip-cr-reviewer.md` — claude-agents-quickquip-cr-reviewer ｜ 关键词：dev、git diff $(git merge-base HEAD dev) HEAD、git diff、docs/dev/branching.md、CLAUDE.md、CONTRIBUTING.md、docs/dev/README.md、docs/dev/documenting.md、docs/dev/style.md、docs/dev/testing.md
- `.github/ISSUE_TEMPLATE/memo.md` → `references/github-issue_template-memo.md` — github-issue_template-memo ｜ 关键词：path/to/file.py
- `.github/PULL_REQUEST_TEMPLATE/release.md` → `references/github-pull_request_template-release.md` — github-pull_request_template-release ｜ 关键词：pyproject.toml、CHANGELOG.md、Unreleased、skills.example/、scripts/maintenance/sync_preset_skills.py、prod.example/、README.md、docs/dev/branching.md、.venv/bin/ruff check .、.venv/bin/python -m pytest -n auto
- `.github/pull_request_template.md` → `references/github-pull_request_template.md` — github-pull_request_template ｜ 关键词：Closes #<issue>、Refs #<issue>、.venv/bin/ruff check .、.venv/bin/python -m pytest -n auto、pnpm --dir frontend type-check、pnpm --dir frontend build
- `prod.example/README.md` → `references/prod.example-readme.md` — 生产配置模板 ｜ 关键词：prod/、prod/docker-compose.yml、.env、sendkey.env.example、prod/sendkey.env、dockerfile: prod/Dockerfile、docker/Dockerfile.prod、prod.example/docker-compose.yml、prod.example/sendkey.env.example、scripts/deploy/
- `scripts/deploy/README.md` → `references/scripts-deploy-readme.md` — QuickQuip Production Template ｜ 关键词：deploy-state.py、quickquip-prod、.env、QUICKQUIP_SEARXNG_BASE_URL、~/.ssh/config、%USERPROFILE%\.ssh\config、ssh quickquip-prod、exit、--host-alias quickquip-prod、-HostAlias quickquip-prod
- `scripts/maintenance/README.md` → `references/scripts-maintenance-readme.md` — 数据与资产维护 ｜ 关键词：backfill_chat_archive.py、--dry-run、backfill_record_identities.py、sync_preset_skills.py、--apply、reset_niuniu_lengths.py、refresh_sts_lexicon.py
- `scripts/ops/README.md` → `references/scripts-ops-readme.md` — 巡检与登录维护 ｜ 关键词：prod/sendkey.env、.env、check_bot_local.sh、check_bot.ps1、check_bot.sh、cron_check_bot.sh、host_metrics_collector.py、data/host_metrics.json、-Server、-RemoteDir
- `scripts/README.md` → `references/scripts-readme.md` — 项目脚本 ｜ 关键词：prod/、bash scripts/deploy/deploy-v4.sh、scripts/deploy/deploy-v4.ps1、bash scripts/ops/check_bot_local.sh、ci/、check/、bash scripts/check/deep-cr-trigger.sh dev、git-hooks/、deploy/server/、deploy/legacy/

