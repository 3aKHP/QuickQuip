<!-- Generated from README.md; do not edit -->

<img align="right" src="docs/assets/brand-mark.svg" width="72" alt="QuickQuip" />

# QuickQuip — QQ 群聊妙语机器人

> 基于 [NoneBot2](https://nonebot.dev) + [OneBot V11](https://github.com/nonebot/adapter-onebot) 的熟人群聊基础设施，用妙语与按需式 AI 工具让群聊更有意思。

QuickQuip（双 Q 谐音 = QQ + Quip／妙语）是一套面向个人与熟人小群自托管的**群聊基础设施**，将确定性群聊互动、按需式多模型 AI 能力与透明可控的运维底座整合为一体：

- **有求才应的交互边界**：规则互动受群开关与滑动窗口限流约束，AI 对话默认仅由显式指令、艾特或引用触发，平时安静待机，需要时随时响应。
- **双层协同的群聊能力**：确定性规则层以零延迟承接作息时区、文字彩蛋、复读接龙与金币小游戏；按需 AI 层兼容四类主流协议，支持人格与群内黑话、长期记忆、本群历史与语录检索、MCP／Skill 工具扩展、多模态处理及周期回顾。
- **面向长期运行的运维底座**：提供 30 页 Web 管理后台、凭据热更新、`qqconf`／`qqsync` 配置同步与多层敏感词防线，配置生效、模型开销与调用链路全程可见可控。

---

## 功能亮点

### 趣味规则与群聊互动

- **时区作息猜测** — 根据“早安”“晚安”等关键词反推全球时区，幽默揭穿群友真实所在地
- **复读检测与互动** — 检测群内复读行为，自动跟读、变体复读或刷屏警告
- **文字彩蛋与语境回复** — 内置 25+ 条支持优先级与加权随机的正则趣味规则（开箱即用[《新三国》全套梗文](docs/user/three-kingdoms-memes.md)），并支持 `regex_context`（正则二次判定）和 `llm_context`（LLM 裁决）语境感知回复
- **STS 公式化回复** — 《杀戮尖塔》梗能力：消息命中“xxx了”时按卡牌名公式回复，`/turmfluch` 生成诅咒文案。详见 [docs/dev/sts-formula.md](docs/dev/sts-formula.md)
- **轻娱乐与日常工具** — `/roll` 掷骰子、`/choose` 随机选择、`/fortune` 每日运势、`/vote` 投票、`/quote` 语录收藏、`/find` 群聊搜索、`/tell` 离线留言、`/wordcloud` 四档群聊词云，以及 6 个公历／农历节日的自动语气切换与问候
- **多贴吧随机搬运** — 维护多贴吧缓存帖子池，支持群内随机抽取与后台定时同步

### 小游戏与金币经济

- **群内小游戏** — Session 型对战涵盖数字炸弹、21 点（Blackjack）、俄罗斯轮盘；持久 RPG 提供牛牛大作战（注册／打胶／击剑／排行）。详见 [docs/user/group-games.md](docs/user/group-games.md)
- **统一金币经济** — 每日签到连击、好感度成长与金币排行榜，所有对战游戏共用下注和结算，参数集中在 `config/games.toml` 配置

### LLM 对话、工具与多模态

- **多协议群聊 Agent** — 兼容 OpenAI / Claude / Gemini / OpenAI Responses 四类协议，支持按群切换渠道、模型与人格（含 Persona v3 拓扑与按需角色百科），提供长期记忆、MCP 桥接、Skill 扩展包、联网搜索（SearXNG 及 Gemini / Claude / Responses 原生搜索）、本群历史与语录按需检索。详见 [docs/dev/llm-module.md](docs/dev/llm-module.md)
- **思考档位与客户端 Profile** — `/llm effort` 按群或私聊调整思考深度；会话身份跨轮次和重启自动延续，四类协议均支持可编辑的[请求指纹 Profile](docs/admin/client-fingerprints.md) 与 HTTP 调用追踪
- **自然的群聊交互节奏** — AI 回复默认引用触发消息，`@名字` 在身份唯一匹配时转为真实艾特（带防打扰冷却）；支持 `/llm delivery` 控制工具过程消息与长回复分段，以及按群配置[低频主动唤醒](docs/admin/configuration.md#configawakeningtoml--群聊低频主动唤醒)
- **多模态输入与创作** — 支持图片理解（含引用与合并转发图片）、语音消息自动转写，以及图片生成、语音合成、写词成曲与 SVG 矢量图本地渲染（统一在 `config/generation.toml` 配置）
- **定时播报与周期回顾** — 按群开启早／午／晚简报、每日约 2000 字总结以及群周报、群月报（支持备选模型自动降级与合并转发失败转长图发送）

### 可视化后台与配置运维

- **Web 管理后台** — 基于 Vue 3 的 30 页管理面板：涵盖 LLM 分区配置工作台（草稿保存、独立发布、Bot 加载确认与渠道定价）、环境变量只写管理与凭据热更新、统计与成本看板、规则与唤醒开关、长期记忆编辑、对话与 Trace 浏览、Skill 管理及诊断探活。详见 [docs/admin/web-admin.md](docs/admin/web-admin.md)
- **工程化配置同步** — 用 [`qqconf`](docs/admin/config-workspace.md)（`unpack`、`refresh`、`pack`）在本地工作副本编辑数据库与原格式配置，配合 [`qqsync`](docs/admin/config-sync.md) 完成三方字段合并、远程同步与中断自动恢复
- **安全与限流防线** — 群级／全局滑动窗口频率限制，配合覆盖模型输入、工具链路、词云及 OneBot 出站接口的[敏感词过滤器](docs/admin/sensitive-filter.md)

完整命令速查：群聊见 [docs/user/group-commands.md](docs/user/group-commands.md)，私聊见 [docs/user/private-commands.md](docs/user/private-commands.md)。全部文档索引见 [docs/index.md](docs/index.md)。

---

## 快速开始

根据运行位置与方式，QuickQuip 支持**本机源码**、**Windows 懒人包**、**本地 Docker** 与**云端 Docker** 四种部署形态（选型对比见[安装与部署方式](docs/admin/installation.md)）。

### 环境要求

- 自备已登录 QQ 的 **OneBot V11 协议端**（连接配置与功能要求见[接入 OneBot V11 协议端](docs/admin/onebot-adapters.md)）
- 源码运行需 **Python** ≥ 3.11（构建 Web 管理后台前端另需 **Node.js** + **pnpm**；Windows 懒人包与 Docker 镜像均已内置运行环境与预构建前端）

> **已有环境升级提示**：升级前请先阅读 [`CHANGELOG.md`](CHANGELOG.md) 对应版本的升级说明，并停止服务备份 `data/` 与 `config/`。若从早期版本跨代升级，涉及配置与运行存储拆分、长期记忆表迁移或旧内置协议端容器拆分时，请分别参照[存储迁移](docs/admin/storage-migration.md)、[长期记忆升级与备份](docs/admin/memory.md#升级与备份)与[协议端迁移](docs/admin/onebot-adapters.md#从随-quickquip-启动的-llbot-迁移)。

### 安装步骤

以下演示使用本机 Python 跑通最小可用环境：

1. **克隆仓库并安装依赖**

   Linux／macOS（Bash）：

   ```bash
   git clone https://github.com/3aKHP/QuickQuip.git QuickQuip
   cd QuickQuip
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   pip install -e .
   ```

   Windows（PowerShell）：

   ```powershell
   git clone https://github.com/3aKHP/QuickQuip.git QuickQuip
   cd QuickQuip
   python -m venv .venv
   .venv/Scripts/python.exe -m pip install -r requirements.txt
   .venv/Scripts/python.exe -m pip install -e .
   ```

   后续命令默认已激活虚拟环境（Windows 下也可直接调用 `.venv/Scripts/python.exe`）。

2. **配置 `.env` 并连接协议端**

   参考 [`.env.example`](.env.example) 在项目根目录创建 `.env`，按[OneBot 接入说明](docs/admin/onebot-adapters.md#连接-quickquip)填写协议端地址与令牌（以下为同机正向 WebSocket 示例，端口按协议端实际配置填写）：

   ```env
   DRIVER=~fastapi+~websockets
   HOST=0.0.0.0
   PORT=8080
   ONEBOT_WS_URLS=["ws://127.0.0.1:3001/"]
   ONEBOT_ACCESS_TOKEN=replace_with_your_token
   WEB_ADMIN_PASSWORD=replace_with_admin_password
   ```

3. **可选：准备 LLM 配置并启动 Web 管理后台**

   如需启用 AI 对话与可视化后台，复制默认人格模板、在 `.env` 中填入所用模型渠道的 API Key（如 `OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`GEMINI_API_KEY`、`DEEPSEEK_API_KEY`），初始化配置数据库并启动后台：

   ```bash
   cp -r config/personas.example config/personas
   python -m quickquip.llm.config_cli init
   cd frontend && pnpm install && pnpm build && cd ..
   python web_api.py
   ```

   保持后台终端运行，浏览器可访问 `http://127.0.0.1:5104/ops/`（详见 [Web 管理后台](docs/admin/web-admin.md)）。

4. **启动机器人**

   另开一个激活同一虚拟环境的终端，在项目根目录运行：

   ```bash
   python bot.py
   ```

   在测试群发送“早安”，收到时区规则回复即表示消息收发正常。

5. **可选：在后台启用第一条 AI 回复**

   用 `WEB_ADMIN_PASSWORD` 登录后台，按[首次启用 LLM](docs/admin/llm-configuration.md#首次启用-llm)添加渠道与模型、选定默认人格，保存草稿并点击“应用到 Bot”。待状态条显示已加载新版本后，由群管理员在群内发送 `/llm on`，再发送 `/ai 请回复“测试成功”` 验证对话（会发起真实模型请求并按渠道计费）。

内置 SearXNG 联网搜索、多模态生成与语音识别（`config/generation.toml`）、群聊主动唤醒（`config/awakening.toml`）及贴吧搬运等可选能力的开启方式见[完整配置参考](docs/admin/configuration.md)。

### Windows 懒人包

GitHub Release 中的 `QuickQuip-*-windows-x64.zip` 已内置 Python、依赖、预构建 Web Admin 前端和 Playwright Chromium：

1. 解压后双击运行 `start.bat`；首次运行会自动从模板生成 `.env`、常用 `config/*.toml`、`config/personas/` 等初始文件并暂停。
2. 打开根目录 `.env`，至少填写 `WEB_ADMIN_PASSWORD`、[协议端连接参数](docs/admin/onebot-adapters.md#连接-quickquip)及所需的模型 API Key。
3. 再次运行 `start.bat` 同时拉起机器人与后台，浏览器打开 `http://127.0.0.1:5104/ops/` 登录管理；如需启用 AI 对话，继续按[首次启用 LLM](docs/admin/llm-configuration.md#首次启用-llm)操作。

懒人包内执行维护命令时使用包目录下的 `python\python.exe`。首次运行的 SmartScreen 放行、后台进程停止命令及日志位置见[安装指南 — Windows 懒人包](docs/admin/installation.md#windows-懒人包)。

### 云端与容器部署

公开分发镜像位于 `ghcr.io/3akhp/quickquip`。本机快速容器部署见[本地 Docker 安装](docs/admin/installation.md#本地-docker-安装)；服务器生产部署以 `prod.example/` 为模板复制出私有 `prod/` 保存实际 Compose 与通知配置，应用层凭据统一维护在根目录 `.env`，发布与巡检通过 `scripts/deploy/`、`scripts/ops/` 执行，完整流程见[云端 Docker 部署指南](docs/admin/deployment.md)。

### 运行测试

```bash
pip install -r requirements-dev.txt   # 首次安装测试依赖
pytest -n auto
```

---

## 架构

```text
src/
├── quickquip/
│   ├── adapters/nonebot/ ← 生命周期、OneBot 消息入口、命令注册、出站守卫
│   ├── app/              ← 应用组合根、消息管线装配
│   │   └── web/          ← Web 管理后台 FastAPI + Vue 3 SPA
│   ├── chat/             ← 规则回复、复读、接龙、节日、统计、聊天归档与报告编排
│   ├── games/            ← 游戏框架、金币经济与各游戏实现
│   ├── llm/              ← LLM 运行时（多协议适配、纪元上下文、工具、MCP、Skill、记忆）
│   ├── generation/       ← 多模态生成、ASR 语音转码与识别、本地 SVG 渲染
│   ├── configuration/    ← 结构化配置存储、生命周期锁与迁移基础设施
│   ├── config_workspace/ ← qqconf 本地配置工作副本编解码与三方合并
│   ├── config_sync/      ← qqsync 跨环境配置同步与发布事务
│   ├── environment/      ← 根 .env 只写管理、消费目录与 env-agent 传输
│   ├── tieba/            ← 贴吧爬虫与帖子池
│   ├── search/           ← SearXNG 与独立联网搜索客户端
│   ├── sts/              ← 杀戮尖塔词表与公式化回复
│   └── common/           ← 限流、去重、持久化、敏感词过滤、最近消息缓冲
└── plugins/              ← NoneBot2 插件发现薄层（仅做 re-export）
```

消息流：`bot.py` → `plugins`（NoneBot2 发现）→ `adapters/nonebot`（事件分发）→ `app`（管线装配）→ `chat` / `games` / `llm` 等领域模块。

规则回复链优先级从高到低：**复读 → 好姐姐接龙 → 自定义接龙 → Session 游戏 → 彩蛋规则 → 语境规则 → 时区猜测 → 杀戮尖塔“xxx了”公式回复**；各环节均受群级规则开关与滑动窗口限流控制。分层规则与数据边界详见 [docs/dev/architecture.md](docs/dev/architecture.md)。

---

## 文档

| 文档 | 说明 |
|------|------|
| [docs/index.md](docs/index.md) | 按角色组织的完整文档导航 |
| [docs/glossary.md](docs/glossary.md) | 项目术语表与核心概念关系 |
| [docs/user/group-commands.md](docs/user/group-commands.md) | 群内指令速查 |
| [docs/user/private-commands.md](docs/user/private-commands.md) | 私聊指令速查 |
| [docs/admin/installation.md](docs/admin/installation.md) | 四种部署形态选型与首次安装入口 |
| [docs/admin/deployment.md](docs/admin/deployment.md) | 云端 Docker 部署与日常运维指南 |
| [docs/admin/onebot-adapters.md](docs/admin/onebot-adapters.md) | OneBot V11 协议端接入与兼容记录 |
| [docs/admin/configuration.md](docs/admin/configuration.md) | 完整配置参考 |
| [docs/admin/llm-configuration.md](docs/admin/llm-configuration.md) | LLM 数据库配置、草稿发布与备份恢复 |
| [docs/admin/environment.md](docs/admin/environment.md) | 环境变量在线管理与凭据热更新 |
| [docs/admin/memory.md](docs/admin/memory.md) | 长期记忆管理与升级备份 |
| [docs/admin/web-admin.md](docs/admin/web-admin.md) | Web 管理后台使用指南 |
| [docs/admin/skills.md](docs/admin/skills.md) | Skill 系统部署与安全模型 |
| [docs/admin/mcp-servers.md](docs/admin/mcp-servers.md) | MCP Server 接入指南 |
| [docs/admin/sensitive-filter.md](docs/admin/sensitive-filter.md) | 敏感词过滤器配置与排障 |
| [docs/dev/README.md](docs/dev/README.md) | 开发者文档与工程规范索引 |
| [docs/dev/adr/README.md](docs/dev/adr/README.md) | 架构决策记录（ADR）索引 |
| [ROADMAP.md](ROADMAP.md) | 演进路线与候选方向 |
| [CHANGELOG.md](CHANGELOG.md) | 版本变更记录 |

---

## 许可证

本项目基于 [WTFPL](LICENSE) 发布 — **Do What The F\*ck You Want To**。Copyright © 2026 [3aKHP](https://github.com/3aKHP)。

---

## 贡献

欢迎提交 Issue 和 Pull Request！开发环境搭建、代码规范与变更分级流程见 [CONTRIBUTING.md](CONTRIBUTING.md)；若只想扩展趣味回复规则，直接编辑 `config/chat_rules.toml`（格式见 `config/chat_rules.toml.example`）即可热重载生效，无需改动消息管线代码。
