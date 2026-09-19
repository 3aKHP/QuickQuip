<!-- Generated index; do not edit. Run: python scripts/ci/sync_self_docs_references.py -->

# QuickQuip 文档索引

与部署版本对齐的公开文档快照，是 self-docs Skill 的路由总表与检索兜底索引。

## 路由指引

- 群友命令、玩法、梗触发 → 用户文档（`docs-user-*`）。
- 部署、配置、运维、报错排查 → 管理文档（`docs-admin-*`）。
- 架构、模块契约、开发约定 → 开发文档（`docs-dev-*`）。
- 项目概览与安装 → `root-readme.md`；版本行为变更 → `root-changelog.md`；计划功能 → `root-roadmap.md`。
- 每条列出该页标题与关键词；`search_skill_resources` 未命中时按关键词挑页，用 `read_skill_resource` 阅读。
- 文档未覆盖的问题如实说明缺失，不要凭训练记忆编造。

## Root 文档

- `CHANGELOG.md` → `references/root-changelog.md` — Changelog ｜ 关键词：python scripts/backfill_record_identities.py、--apply、identities.yaml、/forget、#编号、@QQ 号、(bot)、monthly_report.sample_per_day、monthly_report.input_char_budget、/llm delivery
- `CLAUDE.md` → `references/root-claude.md` — CLAUDE.md — AI 协作者说明 ｜ 关键词：docs/dev/、docs/dev/README.md、docs/dev/branching.md、docs/admin/、docs/user/、prod.example/、prod/、.venv、uv venv、.venv/bin/
- `CODE_OF_CONDUCT.md` → `references/root-code_of_conduct.md` — RFC 325799 — QuickQuip Code of Conduct ｜ 关键词：∀t: Reading(t) → Reading(t)、submit(x) → (User(x) ↔ User(x))、|P| ∈ {0, 1} → ∀p ∈ P: Civil(p, air)、Comply(x) → ¬Violate(x)、Disagree(x) → (C ≡ C)、P(reply) + P(¬reply) = 1
- `CONTRIBUTING.md` → `references/root-contributing.md` — Contributing to QuickQuip ｜ 关键词：docs/dev/README.md、docs/dev/branching.md、docs/dev/style.md、src/、uv venv、uv pip install、.venv/bin/python、.venv/Scripts/python.exe、python、CLAUDE.md
- `README.md` → `references/root-readme.md` — QuickQuip — QQ 群聊妙语机器人 ｜ 关键词：regex_context、llm_context、config/games.toml、/roll、/choose、/fortune、/vote、/quote、/find、/tell
- `ROADMAP.md` → `references/root-roadmap.md` — ROADMAP ｜ 关键词：docs/、reasoning_effort、config/llm.toml、/llm reload、/llm、effect、awakening、chat_rules、llm、generation
- `SECURITY.md` → `references/root-security.md` — 安全策略 / Security Policy ｜ 关键词：dev、-dev.N、-rc.N、cccp1945@vip.qq.com、[QuickQuip security]

## 文档导航

- `docs/index.md` → `references/docs-index.md` — QuickQuip 文档导航 ｜ 关键词：/skill list、.env、llm.toml、generation.toml、awakening.toml、chat_rules.toml、games.toml、sensitive_words.toml、personas/、tool_search

## 用户文档（群友）

- `docs/user/group-commands.md` → `references/docs-user-group-commands.md` — QuickQuip 群内指令速查 ｜ 关键词：/ai 你的问题、/search 关键词、/roll 2d6、/ai、/ai 你觉得今天适合熬夜吗、@机器人 这句话是什么意思、/search news 关键词、/search finance 关键词、/search news OpenAI 最新模型、/defectify
- `docs/user/group-games.md` → `references/docs-user-group-games.md` — QuickQuip 群内游戏指南 ｜ 关键词：config/games.toml、/game start 数字炸弹、/game start 21点 200、/game start 俄罗斯轮盘 200、/注册牛牛、/签到、/金币、/金币排行、/game list、/game stop
- `docs/user/llm-skills.md` → `references/docs-user-llm-skills.md` — AI Skill 扩展能力说明 ｜ 关键词：/ai、/skill list、/ai 你的 /quote 命令怎么用？、/ai 你支持什么配置？、/ai 这个报错是什么意思？、/ai 服务器现在负载高吗？、/ai 内存还剩多少？磁盘快满了吗？、/ai 机器人怎么有点卡，是不是内存不足？
- `docs/user/llm-tool-discovery.md` → `references/docs-user-llm-tool-discovery.md` — AI 工具发现说明 ｜ 关键词：tool_search、tool_list、/ai 帮我查一下这个 GitHub 仓库最近有哪些 PR、/ai 搜一下最近关于某个版本的公告、/ai 查查群里有没有关于阿桃喜欢什么的记忆、/ai 用 GitHub 工具查一下这个项目的 issue
- `docs/user/private-commands.md` → `references/docs-user-private-commands.md` — QuickQuip 私聊指令速查 ｜ 关键词：/ai、/start_session、/end_session、/resume_session、<尖括号>、[方括号]、/resume_session [N]、/sessions、/delete_session N、/start_session --preset "请用英文回复"
- `docs/user/three-kingdoms-memes.md` → `references/docs-user-three-kingdoms-memes.md` — 新三国梗触发指南

## 管理文档（部署与运维）

- `docs/admin/configuration.md` → `references/docs-admin-configuration.md` — QuickQuip 配置参考 ｜ 关键词：DRIVER、~websockets、~fastapi+~websockets、HOST、0.0.0.0、PORT、8080、QQ_ACCOUNT、ONEBOT_WS_URLS、ONEBOT_ACCESS_TOKEN
- `docs/admin/deployment.md` → `references/docs-admin-deployment.md` — QuickQuip 云端部署指南 ｜ 关键词：prod/deploy-v4.sh、prod/deploy-v4.ps1、--migrate、--skip-health、-Rollback -ReleaseId <id>、-DryRun、-Status、bash prod/deploy-v4.sh --help、pyproject.toml、1.15.3-dev.2+build.20260909.065235
- `docs/admin/game-config.md` → `references/docs-admin-game-config.md` — 游戏系统管理 ｜ 关键词：data/、src/quickquip/games/、/game list、/game stop、/disable <rule_name>、/enable <rule_name>、src/quickquip/app/message_pipeline.py、game_registry.register()、config/games.toml、config/games.toml.example
- `docs/admin/mcp-servers.md` → `references/docs-admin-mcp-servers.md` — MCP Server 接入指南 ｜ 关键词：http、url、headers、stdio、command、args、env、docker、image、mounts
- `docs/admin/migration-napcat-to-llbot.md` → `references/docs-admin-migration-napcat-to-llbot.md` — NapCat → LLBot 迁移指南 ｜ 关键词：mlikiowa/napcat-docker、initialencounter/llonebot:v7.12.14-7.3.2-45758、docker-compose.example.yml、docker-compose.yml、entrypoint、/bin/sh -c、llbot-data/default_config.json、http://<服务器IP>:3080、docker exec、data/config_<QQ号>.json
- `docs/admin/onebot-adapters.md` → `references/docs-admin-onebot-adapters.md` — OneBot 适配器状态与选择 ｜ 关键词：.env、ONEBOT_WS_URLS、DRIVER、~websockets、~fastapi、ws://<bot 地址>:8080/onebot/v11/ws、ONEBOT_ACCESS_TOKEN、message.group、sender.card、nickname
- `docs/admin/record-identities.md` → `references/docs-admin-record-identities.md` — 记录身份迁移与验收 ｜ 关键词：requirements.txt、--database、memories、quotes、offline_messages、all、data/llm.db、data/quotes.db、data/offline_messages.db、--path
- `docs/admin/sensitive-filter.md` → `references/docs-admin-sensitive-filter.md` — 敏感词过滤器（sensitive_filter） ｜ 关键词：Content Exists Risk、Content security warning、src/quickquip/common/sensitive_filter.py、config/sensitive_words.toml、[内容已屏蔽]、casefold()、political_leaders、political_events、territorial、ethnic_religion
- `docs/admin/skills.md` → `references/docs-admin-skills.md` — Skill 系统（skills/） ｜ 关键词：skills/、SKILL.md、references/、scripts/、skills.example/、config/personas.example/、config/personas/、prod.example/、^[a-z0-9][a-z0-9-]*$、name
- `docs/admin/tool-discovery.md` → `references/docs-admin-tool-discovery.md` — LLM 工具发现配置 ｜ 关键词：tool_search、config/llm.toml、enabled、enabled_mode = "replace"、discovery_mode、off、on、auto、discovery_min_tools、discovery_search_limit
- `docs/admin/web-admin.md` → `references/docs-admin-web-admin.md` — Web Admin 管理后台 ｜ 关键词：/ops/、auth_basic、GET /ops/api/auth/me、WEB_ADMIN_PASSWORD、Set-Cookie、/ops/api/*、data/web_admin_sessions.db、session_id、localStorage、HttpOnly

## 开发文档

- `docs/dev/architecture.md` → `references/docs-dev-architecture.md` — QuickQuip 项目架构与结构 ｜ 关键词：README.md、style.md、pip install -e .、python bot.py、.env、prod/、src/quickquip/adapters/nonebot/、src/plugins/、repeat_detector、good_girl_chain
- `docs/dev/branching.md` → `references/docs-dev-branching.md` — QuickQuip 开发工作流与发布流程 ｜ 关键词：dev、main、style.md、architecture.md、versioning.md、feat、fix、refactor、.env、data/
- `docs/dev/game-framework.md` → `references/docs-dev-game-framework.md` — 游戏框架开发者指南 ｜ 关键词：BaseGame、src/quickquip/app/message_pipeline.py、OrderedDict[str, Session]、group_id、src/quickquip/adapters/nonebot/commands.py、command_parts/、config/games.toml、src/quickquip/games/config.py、config.py、GameConfig
- `docs/dev/llm-module.md` → `references/docs-dev-llm-module.md` — QuickQuip LLM 模块说明 ｜ 关键词：google_search、LLM_TRACE_FLAG_FILE、data/llm_trace.db、run_tool_call_loop、trigger_kind、group_direct、private_direct、group_passive、interrupted、request_cancelled
- `docs/dev/mcp-integration.md` → `references/docs-dev-mcp-integration.md` — QuickQuip MCP 集成说明 ｜ 关键词：config/llm.toml、[[mcp.servers]]、stdio、docker、http、sse、${ENV_VAR}、${ENV_VAR:-default}、ToolRegistry、/llm mcp status
- `docs/dev/mcp-tutorial.md` → `references/docs-dev-mcp-tutorial.md` — 从零理解 MCP —— 以 QuickQuip 项目为例 ｜ 关键词：llm-module.md、src/quickquip/llm/mcp/、src/quickquip/llm/config.py、src/quickquip/llm/service_parts/mcp_lifecycle.py、。配置权威模板为、MCPClient、mcp/client.py、ToolRegistry、mcp_*、tools/list
- `docs/dev/README.md` → `references/docs-dev-readme.md` — QuickQuip 开发者文档 ｜ 关键词：docs/dev/、architecture.md、style.md、branching.md、versioning.md、record-identities.md、llm-module.md、mcp-integration.md、tool-discovery.md、game-framework.md
- `docs/dev/record-identities.md` → `references/docs-dev-record-identities.md` — 记录正文与成员身份契约 ｜ 关键词：private:<QQ>、common/identity.py、common/identity_sources.py、app/identities.py、llm/identity.py、LLMService.group_identities()、/llm reload、data/stats.json、common/record_content.py、common/record_search.py
- `docs/dev/regex-tutorial.md` → `references/docs-dev-regex-tutorial.md` — 从零开始学习正则表达式 —— 以 QuickQuip 项目为例 ｜ 关键词：src/quickquip/、src/plugins/、config/chat_rules.toml、config/chat_rules.toml.example、src/quickquip/chat/config.py、src/quickquip/chat/text_rules.py、你的、玩原神玩的、原神怎么你了、原神
- `docs/dev/skill-tutorial.md` → `references/docs-dev-skill-tutorial.md` — 从零开始编写 Skill —— 以 QuickQuip 项目为例 ｜ 关键词：src/quickquip/llm/skills/、parser.py、catalog.py、tools/、src/quickquip/llm/service_parts/skills.py、/skill、config/llm.toml.example、[skills]、skills/、skills.example/self-docs
- `docs/dev/sts-formula.md` → `references/docs-dev-sts-formula.md` — STS 公式化回复模块 ｜ 关键词：quickquip.sts、chat/、llm/、formulas/card_le/、formulas/defectify/、/defectify、nkhoit/spire-archive、scripts/refresh_sts_lexicon.py、src/quickquip/sts/sts_lexicon.json、SOURCE_SHA
- `docs/dev/style.md` → `references/docs-dev-style.md` — QuickQuip 代码规范与架构原则 ｜ 关键词：architecture.md、branching.md、line-length = 100、E + F、any、data/、.env、prod/、utils.py、helpers.py
- `docs/dev/tool-discovery.md` → `references/docs-dev-tool-discovery.md` — LLM 工具发现实现说明 ｜ 关键词：tool_search、tool_list、LLMRequest.tools、src/quickquip/llm/tools.py、ToolManifestEntry、src/quickquip/llm/tool_registry.py、src/quickquip/llm/service_parts/tools.py、src/quickquip/llm/tool_discovery.py、loaded_names、src/quickquip/llm/tool_loop.py
- `docs/dev/versioning.md` → `references/docs-dev-versioning.md` — QuickQuip 版本号约定 ｜ 关键词：Major.Minor.Patch、branching.md、pyproject.toml、version、frontend/package.json、1.15.1-dev.0、1.15.1-dev.1、1.15.1-rc.1、1.15.1、1.16.0-dev.0

## 其他

- `.claude/agents/quickquip-cr-reviewer.md` → `references/claude-agents-quickquip-cr-reviewer.md` — claude-agents-quickquip-cr-reviewer ｜ 关键词：dev、git diff $(git merge-base HEAD dev) HEAD、git diff、CLAUDE.md、CONTRIBUTING.md、docs/dev/README.md、docs/dev/style.md、docs/dev/architecture.md、docs/dev/branching.md、llm-module.md
- `.github/ISSUE_TEMPLATE/memo.md` → `references/github-issue_template-memo.md` — github-issue_template-memo ｜ 关键词：path/to/file.py
- `.github/PULL_REQUEST_TEMPLATE/release.md` → `references/github-pull_request_template-release.md` — github-pull_request_template-release ｜ 关键词：vX.Y.Z、pyproject.toml、CHANGELOG.md、Unreleased、prod.example/、README.md、.venv/bin/ruff check .、.venv/bin/python -m pytest -n auto、pnpm --dir frontend type-check、pnpm --dir frontend build
- `.github/pull_request_template.md` → `references/github-pull_request_template.md` — github-pull_request_template ｜ 关键词：Closes #<issue>、Refs #<issue>、.venv/bin/ruff check .、.venv/bin/python -m pytest -n auto、pnpm --dir frontend type-check、pnpm --dir frontend build
- `prod.example/README.md` → `references/prod.example-readme.md` — QuickQuip Production Template ｜ 关键词：prod/、.env、prod/prod.example、deploy-state.py、quickquip-prod、config/llm.toml、QUICKQUIP_SEARXNG_BASE_URL、remote-deploy-v4.sh、bash prod/deploy-v4.sh、prod/deploy-v4.ps1

