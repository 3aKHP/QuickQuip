---
project: "QuickQuip"
branch: "main"
---

# CLAUDE.md — AI 协作者说明

QuickQuip 是基于 NoneBot2 + OneBot V11 的轻量 QQ 群聊机器人。规则优先：文字 meme、复读检测、接龙游戏、时区猜测为骨架；LLM 聊天为可选 opt-in 层。Python ≥ 3.11。

## 相关文档

| 想看... | 去哪里 |
|---|---|
| 架构设计、分层、消息流 | `docs/dev/` |
| 部署与运维配置 | `docs/admin/` |
| 用户向命令与功能说明 | `docs/user/` |
| 公开生产运维模板 | `prod.example/` |
| 真实生产运维资产 | `prod/`（已 gitignored） |

## 环境

- **Windows 设备**。Shell 默认用 `pwsh.exe`（PowerShell 7+），不要用 bash。`&&` 用 `;` 替代，路径分隔符用 `/`
- **优先使用项目 `.venv`**。运行 Python 命令前激活：`.venv/Scripts/activate`，或直接用 `.venv/Scripts/python -m pytest` 等
- **项目采用 src layout**：源码位于 `src/quickquip/` 和 `src/plugins/`，开发时需 `pip install -e .`（可编辑安装）或设 `PYTHONPATH=src`
- **不主动 push**。即使刚 commit 完，也等用户明确说"请推"
- **不 squash merge**。合并 PR 用 `gh pr merge --merge`，保留完整分支历史

### 私有目录边界

- `prod.example/` 是可公开分发的生产运维模板；`prod/` 是真实生产运维目录，不提交。
- 根目录 `.env` 是 QuickQuip 应用层唯一涉密凭证来源；`prod/sendkey.env` 只供运维巡检/通知脚本使用。
- 本地开发辅助目录（草稿/沙箱/私有材料）由开发者自行建立并排除，机制见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

### Shell 降级策略

1. **优先用原生 PowerShell 工具**（`PowerShell` 指令），直接写 pwsh 7 语法
2. 遇到引号转义或复杂管道问题时，**降级为** `pwsh.exe -Command "..."` 通过 Bash 工具调用
3. 反复出错时，**写入 `.ps1` 临时文件再执行**，避免多层转义
4. **严禁**在 PowerShell 中使用 Unix 重定向语法（`2>/dev/null`、`>&2` 等），用 `2>$null`、`$ErrorActionPreference` 替代

## 启动准则

- **需明确指令才 Commit**。讨论中提到"要提交"不算，必须出现"请提交 / 请 commit"这类祈使句

### 分支策略

项目采用**精简 GitFlow**：常驻 `dev`（集成）+ `main`（发布）两条分支。

- **feat/fix/refactor**：从 `dev` 拉分支，PR 回 `dev`
- **chore/docs 小修补**：直接 push 到 `dev`（走 PR 也可，利于触发 CI）
- **main 仅接收 release PR 和紧急 hotfix**，禁止直接 push 日常改动
- 发版时开 `dev → main` 的 release PR，main 打 tag 后 back-merge 回 dev

完整流程、release checklist、hotfix 例外条件见 [`docs/dev/branching.md`](docs/dev/branching.md)。分支命名：`<type>/<topic>` 或 `<type>/v<version>-<topic>`，例 `feat/v1.9.0-proxy-support`

## 常用命令

所有命令优先通过 `.venv` 执行。若未激活虚拟环境，用 `.venv/Scripts/python -m <module>` 调用。

```bash
.venv/Scripts/pip install -r requirements.txt       # 安装依赖
.venv/Scripts/pip install -r requirements-dev.txt   # 安装开发依赖
.venv/Scripts/pip install -e .                      # 可编辑安装（src layout 必须）
.venv/Scripts/python bot.py                         # 启动 bot
.venv/Scripts/python -m pytest -n auto              # 并行运行测试
.venv/Scripts/python -m pytest -m playwright        # 包含浏览器测试
.venv/Scripts/ruff check .                          # Lint
```

## 架构速览

项目采用 src layout，源码位于 `src/` 目录下：

```
src/
├── quickquip/
│   ├── chat/          # 规则引擎：text_rules, repeat_detector, chain_game, context_rules, wordcloud, daily_summary/briefing
│   ├── common/        # 共享工具：rate_limit, persistence, message_deduper, sensitive_filter
│   ├── llm/           # LLM 运行时：provider, service, config, store, mcp, tool_registry, tool_loop, prompting, settings
│   ├── games/         # 游戏系统：niuniu, blackjack, russian_roulette, number_bomb, economy, scores, registry
│   ├── generation/    # 多模态生成：image, audio, music, asr
│   ├── tieba/         # 贴吧爬虫（Playwright）
│   ├── search/        # 联网搜索（SearXNG）
│   ├── adapters/nonebot/  # NoneBot2 适配层：matcher 注册、命令处理、scheduler、lifecycle
│   └── app/           # 应用组装：管线实例化、Web Admin（FastAPI + Vue 3 SPA）
└── plugins/           # NoneBot2 插件入口 shim，re-export 指向 quickquip.*
```

三层结构：
- `quickquip/chat|common|llm|games|generation|tieba|search` — 框架无关的业务逻辑（包路径不变，`from quickquip.xxx import ...`）
- `quickquip/adapters/nonebot/` — NoneBot2 handler 注册（直接 import `nonebot`，与业务层隔离）
- `plugins/` — NoneBot2 插件入口 shim，每个文件只是 re-export 指向 `quickquip.*`

开发环境需先运行 `pip install -e .`（可编辑安装），让 Python 能解析 `src/` 下的包。

消息流：`NoneBot2 event → group_messages → resolve_reply()`（规则链：repeat → chain → text_rules → context_rules → timezone），每条经 `rule_switch.is_enabled()` 和 `rate_limit.allow()` 检查。LLM 触发时走 `llm_service.generate_reply()`。

## Commit 规范

格式：`<type>(<scope>): <subject>`，Conventional Commits。多行 body 用 pwsh here-string：

```pwsh
git commit -m @"
feat(llm): add proxy support to ProviderConfig

Optional HTTP(S) proxy field; all HTTP requests route through ProxyHandler opener.
"@
```

- **type**：`feat` / `fix` / `refactor` / `docs` / `chore` / `test` / `style` / `perf`
- **scope** 常用：`llm` / `chat` / `games` / `web-admin` / `niuniu` / `tieba` / `ci` / `docs`
- 不用 `--amend`（除非用户明确要求）；pre-commit hook 失败时不加 `--no-verify`

## CHANGELOG 规范

- feat/fix/refactor 级改动**不直接编辑 `CHANGELOG.md`**，改记一条本地草稿（机制见 [`CONTRIBUTING.md`](CONTRIBUTING.md)），避免并行分支在 `## [Unreleased]` 处冲突
- 每条**一行**，只写"做了什么"和"为什么重要"，不写文件路径和实现细节
- PR 描述里附上该条目正文，便于 review
- release 时由协作者汇总本地草稿（主）与已合并 commit 历史（兜底），按 `### 新增` / `### 变更` / `### 修复` / `### 移除` 分组写入 `CHANGELOG.md` 新版本段，并清掉已发布草稿
- chore/docs/style 不更新 CHANGELOG

## 敏感词文件保护

`config/sensitive_words.toml` 是 LLM 敏感词过滤的词表文件，**禁止 Read/Edit/Write/Grep**。仓库只提供 `.example` 模板，真实词表已 gitignored 且仅存于部署机器。

调试过滤器时：用测试 fixtures（`tests/unit/common/test_sensitive_filter.py`）中的合成词表，或查看运行时日志（`logger=quickquip.common.sensitive_filter`，只记录类别和 SHA-256 前缀）。
