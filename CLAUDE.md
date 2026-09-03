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
| 开发文档职责与公共/私有边界 | `docs/dev/README.md` |
| 变更分级、评审与发布流程 | `docs/dev/branching.md` |
| 部署与运维配置 | `docs/admin/` |
| 用户向命令与功能说明 | `docs/user/` |
| 公开生产运维模板 | `prod.example/` |
| 真实生产运维资产 | `prod/`（已 gitignored） |

## 环境

- **Linux 环境（WSL2）**。Shell 用 bash，路径分隔符 `/`
- **环境与依赖用 uv 管理**。`.venv` 由 `uv venv` 创建（Linux 布局 `.venv/bin/`），依赖用 `uv pip install` 安装。**日常运行直接用 `.venv/bin/python`**（或激活 `.venv/bin/activate` 后直接 `python`）；不把 `uv run` 用于日常命令，以免触发 uv 项目模式生成 `uv.lock`（已永久 gitignore）。跨平台 pre-push hook 例外，仍用 `uv run`
- **项目采用 src layout**：源码位于 `src/quickquip/` 和 `src/plugins/`，开发时需 `uv pip install -e .`（可编辑安装）或设 `PYTHONPATH=src`
- **不主动 push**。即使刚 commit 完，也等用户明确说“请推”
- **不 squash merge**。合并 PR 用 `gh pr merge --merge`，保留完整分支历史

### 私有目录边界

- `prod.example/` 是可公开分发的生产运维模板；`prod/` 是真实生产运维目录，不提交。
- 根目录 `.env` 是 QuickQuip 应用层唯一涉密凭证来源；`prod/sendkey.env` 只供运维巡检/通知脚本使用。
- 本地开发辅助目录（草稿/沙箱/私有材料）由开发者自行建立并排除，机制见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

## 启动准则

- **需明确指令才 Commit**。讨论中提到“要提交”不算，必须出现“请提交 / 请 commit”这类祈使句

### 分支策略

项目采用**精简 GitFlow**：常驻 `dev`（集成）+ `main`（发布）两条分支。

- **feat/fix/refactor**：从 `dev` 拉分支，PR 回 `dev`
- **chore/docs 小修补**：直接 push 到 `dev`（走 PR 也可，利于触发 CI）
- **main 仅接收 release PR 和紧急 hotfix**，禁止直接 push 日常改动
- 发版时开 `dev → main` 的 release PR，main 打 tag 后 back-merge 回 dev

完整流程、变更分级、release checklist、hotfix 例外条件见 [`docs/dev/branching.md`](docs/dev/branching.md)。chore/docs 小修补可走 Develop direct；其他变更按 Quick PR、Standard PR、Huge PR、Hot-Fix 或 Release 分级执行。分支命名：`<type>/<topic>` 或 `<type>/v<version>-<topic>`，例 `feat/v1.9.0-proxy-support`

## 常用命令

环境用 `uv venv` / `uv pip install` 创建与装依赖；日常命令直接调 `.venv/bin/python`（或激活 `.venv/bin/activate` 后用 `python`）。

```bash
uv venv                                            # 创建虚拟环境（首次）
uv pip install -r requirements-dev.txt             # 安装依赖（含运行时）
uv pip install -e .                                # 可编辑安装（src layout 必须）
.venv/bin/python bot.py                            # 启动 bot
.venv/bin/python -m pytest -n auto                 # 并行运行测试
.venv/bin/python -m pytest -m playwright           # 包含浏览器测试
.venv/bin/ruff check .                             # Lint
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
│   ├── generation/    # 多模态生成：image, audio, music, asr, svg
│   ├── tieba/         # 贴吧爬虫（Playwright）
│   ├── search/        # 联网搜索（SearXNG）
│   ├── sts/           # 杀戮尖塔公式化回复（lexicon、formulas）
│   ├── adapters/nonebot/  # NoneBot2 适配层：matcher 注册、命令处理、scheduler、lifecycle
│   └── app/           # 应用组装：管线实例化、Web Admin（FastAPI + Vue 3 SPA）
└── plugins/           # NoneBot2 插件入口 shim，re-export 指向 quickquip.*
```

三层结构：
- `quickquip/chat|common|llm|games|generation|tieba|search` — 框架无关的业务逻辑（包路径不变，`from quickquip.xxx import ...`）
- `quickquip/adapters/nonebot/` — NoneBot2 handler 注册（直接 import `nonebot`，与业务层隔离）
- `plugins/` — NoneBot2 插件入口 shim，每个文件只是 re-export 指向 `quickquip.*`

开发环境需先运行 `uv pip install -e .`（可编辑安装），让 Python 能解析 `src/` 下的包。

消息流：`NoneBot2 event → group_messages → resolve_reply()`（规则链：repeat → good_girl_chain → custom_chain_games → games registry → text_rules → context_rules → timezone → STS card_le（链尾，规则开关与限频预检通过后才匹配，不得抢占时区等具体规则）），每条经 `rule_switch.is_enabled()` 和 `rate_limit.allow()` 检查。LLM 触发时走 `llm_service.generate_reply()`。

## Commit 规范

格式：`<type>(<scope>): <subject>`，Conventional Commits。多行 body 用多个 `-m` 分隔（每个 `-m` 为一段）：

```bash
git commit -m "feat(llm): add proxy support to ProviderConfig" \
  -m "Optional HTTP(S) proxy field; all HTTP requests route through ProxyHandler opener."
```

- **type**：`feat` / `fix` / `refactor` / `docs` / `chore` / `test` / `style` / `perf`
- **scope** 常用：`llm` / `chat` / `games` / `web-admin` / `niuniu` / `tieba` / `ci` / `docs`
- 不用 `--amend`（除非用户明确要求）；pre-commit hook 失败时不加 `--no-verify`

## CHANGELOG 规范

- feat/fix/refactor 级改动**不直接编辑 `CHANGELOG.md`**，改记一条本地草稿（机制见 [`CONTRIBUTING.md`](CONTRIBUTING.md)），避免并行分支在 `## [Unreleased]` 处冲突
- 每条**一行**，只写“做了什么”和“为什么重要”，不写文件路径和实现细节
- PR 描述里附上该条目正文，便于 review
- release 时由协作者汇总本地草稿（主）与已合并 commit 历史（兜底），按 `### ✨ 新增 (Added)` / `### 🔧 变更 (Changed)` / `### 🐛 修复 (Fixed)` / `### 🗑️ 移除 (Removed)` 分组写入 `CHANGELOG.md` 新版本段（沿用既有版本段的双语 emoji 小节形态），并清掉已发布草稿
- chore/docs/style 不更新 CHANGELOG

## 敏感词文件保护

`config/sensitive_words.toml` 是 LLM 敏感词过滤的词表文件，**禁止 Read/Edit/Write/Grep**。仓库只提供 `.example` 模板，真实词表已 gitignored 且仅存于部署机器。

调试过滤器时：用测试 fixtures（`tests/unit/common/test_sensitive_filter.py`）中的合成词表，或查看运行时日志（`logger=quickquip.common.sensitive_filter`，只记录类别和 SHA-256 前缀）。

## 隐私 ID 保护

真实 QQ 群号、QQ 号、以及其他能定位到具体个人或群组的标识符，**禁止**出现在任何会进入公开仓库的内容里：源码、测试、文档、示例配置、commit message、PR 描述与评论。测试与示例统一使用合成段（`1000000000`/`1000000001`、`123456`、`987654321` 等）。真实 ID 只允许存在于 gitignored 的本地私有材料中，不进入版本控制。

仓库用 `scripts/ci/check_id_literals.py` 在 CI 与 pre-push 中拦截公开文件里的 9–11 位数字字面量（白名单仅含上述合成值）；另有可选的 pre-commit 模板 `scripts/git-hooks/pre-commit`，从 gitignored 的根目录 `.redact-ids` 读取真实 ID 列表做提交前拦截，该列表本身不进仓库。
