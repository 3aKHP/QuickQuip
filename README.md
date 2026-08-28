<img align="right" src="docs/assets/brand-mark.svg" width="72" alt="QuickQuip" />

# QuickQuip — QQ 群聊妙语机器人

> 基于 [NoneBot2](https://nonebot.dev) + [OneBot V11](https://github.com/nonebot/adapter-onebot) 的 QQ 群聊互动机器人，用妙语让群聊更有趣。

QuickQuip（双 Q 谐音 = QQ + Quip/妙语）是一个**轻量级、规则驱动优先**的 QQ 群聊机器人。它通过精心设计的正则匹配和状态机自动给出幽默回复，同时支持按群启用 LLM 扩展，可通过指令或艾特触发多模型对话。

---

## 功能亮点

- **时区作息猜测** — 根据"早安""晚安"等关键词反推全球时区，幽默揭穿群友真实所在地
- **复读检测与互动** — 检测群内复读行为，自动跟读、变体复读或刷屏警告
- **文字彩蛋规则** — 内置 25+ 条基于正则的趣味回复规则，支持优先级和加权随机，开箱即用《新三国》全套梗文。详见 [docs/user/three-kingdoms-memes.md](docs/user/three-kingdoms-memes.md)
- **语境感知回复** — 支持 `regex_context`（正则二次判定）和 `llm_context`（LLM yes/no 裁决）两种模式
- **群内小游戏** — Session 型对战：数字炸弹 / 21 点（Blackjack）/ 俄罗斯轮盘；持久 RPG：牛牛大作战（注册/打胶/击剑/排行）。全部接入金币经济系统，详见 [docs/user/group-games.md](docs/user/group-games.md)
- **金币经济系统** — 每日签到累加连击、好感度成长、金币排行，所有对战游戏共用下注和结算。参数集中在 `config/games.toml` 配置
- **节日自动化** — 内置 6 个节日（公历+农历），自动切换 bot 语气并发送 persona 口吻问候
- **轻娱乐与互动** — `/roll` 掷骰子、`/choose` 随机选择、`/fortune` 每日运势、`/vote` 投票、`/quote` 语录收藏、`/find` 群聊搜索、`/tell` 离线留言
- **词云生成** — `/wordcloud` 按 today/week/month/year 四档生成群聊词云图片
- **STS 公式化回复** — 《杀戮尖塔》梗能力：消息命中"xxx了"时按卡牌名公式回复，`/turmfluch` 一次性生成诅咒文案（v1.10）。详见 [docs/dev/sts-formula.md](docs/dev/sts-formula.md)
- **LLM 扩展** — 兼容 OpenAI / Claude / Gemini 协议，按群切换 provider/model/persona，支持工具调用、MCP 桥接、图片理解、语音消息转写、联网搜索、故障机器人转写。详见 [docs/dev/llm-module.md](docs/dev/llm-module.md)
- **低频唤醒** — 按群配置唤醒延长、兴趣话题、相关性/答疑判定、无聊冒泡和兜底概率，所有入口受规则开关与限流保护
- **LLM 用量/成本看板** — 全链路 token 计量与成本估算，按 provider/功能/模型/群/人格五维归因，Web Admin 提供用量面板与定价状态展示
- **每日播报与总结** — 按群开启早/中/晚报和每日 2000 字小作文，模型级联失败自动降级
- **群周报与月报** — 每周/每月自动生成上一周期的群聊回顾，分天采样覆盖全周期，热词趋势与群内大事记一目了然
- **多贴吧随机搬运** — 多来源帖子池维护，支持随机抽取和定时同步
- **多模态能力** — 图片生成、语音合成、语音识别、歌词创作与音乐生成、SVG 矢量图本地渲染（LLM `draw_svg` 工具），统一收口 `config/generation.toml`
- **Web 管理后台** — Vue 3 SPA 仪表板：统计、规则开关、唤醒管理、记忆编辑、对话浏览、配置在线编辑、词云生成、用量看板、诊断工具、日志浏览。详见 [docs/admin/web-admin.md](docs/admin/web-admin.md)
- **频率限制** — 滑动窗口限流保护，支持按群独立分桶（`scope = "group"`）或全局合并（`scope = "global"`）

完整命令速查：群聊见 [docs/user/group-commands.md](docs/user/group-commands.md)，私聊见 [docs/user/private-commands.md](docs/user/private-commands.md)。  
全部文档索引见 [docs/index.md](docs/index.md)。

---

## 快速开始

### 环境要求

- **Python** ≥ 3.11
- **NoneBot2** + **OneBot V11 适配器**
- OneBot V11 协议实现端（推荐 [LLBot](https://github.com/LLOneBot/LuckyLilliaBot)，备选 [NapCat](https://github.com/NapNeko/NapCatQQ)）

### 安装步骤

1. **克隆仓库**

   ```bash
   git clone https://github.com/3aKHP/QuickQuip.git QuickQuip
   cd QuickQuip
   ```

2. **创建虚拟环境并安装依赖**

   ```bash
   python -m venv .venv
   # Windows: .venv\Scripts\activate  |  Linux/macOS: source .venv/bin/activate
   pip install -r requirements.txt
   pip install -e .     # 可编辑安装（src layout 必须）
   ```

3. **配置环境变量**

   在项目根目录创建 `.env` 文件，参考 NoneBot2 文档配置连接参数：

   ```env
   DRIVER=~fastapi+~websockets
   HOST=0.0.0.0
   PORT=8080
   SEARXNG_BASE_URL=http://127.0.0.1:8888
   ```

4. **可选：启动项目内置 SearXNG**

   需先在 `.env` 中设置 `SEARXNG_SECRET`（compose 启动时必填）：

   ```bash
   docker compose -f docker-compose.example.yml up -d searxng
   ```

   默认暴露到 `http://127.0.0.1:8888`，开启 JSON 搜索接口。

5. **可选：启用 LLM**

   复制 `config/llm.toml.example` 为 `config/llm.toml`，复制 `config/personas.example/` 为 `config/personas/`，填入中转 URL、模型列表和人格定义。在 `.env` 中配置相应 API key：

   ```env
   OPENAI_API_KEY=your_key
   ANTHROPIC_API_KEY=your_key
   GEMINI_API_KEY=your_key
   DEEPSEEK_API_KEY=your_key
   ```

   完整配置参考见 [docs/admin/configuration.md](docs/admin/configuration.md)。

6. **可选：启用图片/语音/音乐生成和语音识别**

   复制 `config/generation.toml.example` 为 `config/generation.toml`，按注释填入 provider 和模型。不存在时图片部分回退读取 `llm.toml` 旧版配置。

7. **可选：启用群聊唤醒**

   复制 `config/awakening.toml.example` 为 `config/awakening.toml`，按群设置唤醒延长、兴趣话题、相关性判定、答疑判定和无聊唤醒参数。群内可用 `/awakening status` 查看生效状态。

8. **可选：启用多贴吧搬运**

   安装 Playwright 浏览器：

   ```bash
   python -m playwright install chromium
   ```

   在 `.env` 中配置：

   ```env
   TIEBA_ENABLED=true
   TIEBA_FORUM_KEYWORDS=贴吧名1,贴吧名2
   TIEBA_SYNC_INTERVAL_SECONDS=900
   TIEBA_BROWSER_HEADLESS=true
   ```

   首次使用前运行 `python -m quickquip.tieba.login`，或按 [部署指南](docs/admin/deployment.md) 完成贴吧登录态导出。

9. **可选：启动 Web 管理后台**

   ```bash
   # 先构建前端（需 Node.js + pnpm）
   cd frontend && pnpm install && pnpm build && cd ..

   # 在 .env 中设置管理口令
   # WEB_ADMIN_PASSWORD=your-password

   # 启动管理 API
   python web_api.py
   ```

   访问 `http://127.0.0.1:5104/ops/`。详见 [docs/admin/web-admin.md](docs/admin/web-admin.md)。

10. **启动机器人**

   ```bash
   python bot.py
   ```

### Windows 懒人包

Release 中的 `QuickQuip-*-windows-x64.zip` 内置 Python、依赖、Web Admin 前端和 Playwright Chromium。解压后运行 `start.bat`，首次运行会从示例文件生成 `.env`、常用 `config/*.toml`、`config/personas/` 与资料文件并暂停；请至少在 `.env` 中填写 `WEB_ADMIN_PASSWORD`、OneBot 连接配置和需要的 API key，再次运行 `start.bat` 启动。

首次运行注意：

- **SmartScreen 提示**：浏览器下载的 ZIP 带 Mark-of-the-Web，解压后首次运行 `start.bat`（或内嵌 python）可能弹出「Windows 已保护你的电脑」——点「更多信息」→「仍要运行」即可；用命令行 `tar` 解压则不会传播该标记。
- **停止方式**：前台控制台（QQ Bot）按 `Ctrl+C`；Web Admin 是后台进程，关掉管理窗口不会带走它，需在 PowerShell 执行
  `Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -match 'web_api.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId }`。
- 运行期间任务栏会有一个最小化的「QuickQuip Admin」cmd 窗口（Web Admin 的启动壳），属正常现象，随 Web Admin 退出自动关闭；Web Admin 运行日志追加在 `data\web-admin.log`（无轮转）。

生产部署模板位于 `prod.example/`；公开分发镜像位于 `ghcr.io/3akhp/quickquip`。如需使用私有 compose、部署脚本和巡检脚本，先复制为 gitignore 的 `prod/`，应用密钥仍统一维护在根目录 `.env`。详见 [docs/admin/deployment.md](docs/admin/deployment.md)。

### 运行测试

```bash
pip install -r requirements-dev.txt   # 测试依赖（首次）
pytest -n auto
```

---

## 架构

```
src/
├── quickquip/
│   ├── adapters/nonebot/ ← 生命周期、消息入口、命令注册
│   ├── app/              ← 应用级消息管线与共享状态装配
│   │   └── web/          ← Web 管理后台 FastAPI + Vue 3 SPA
│   ├── chat/             ← 规则回复（复读、接龙、彩蛋、节日、时区、统计）
│   ├── games/            ← 游戏模块（registry、scores、economy、各游戏实现）
│   ├── llm/              ← LLM 运行时（provider、MCP、工具调用、记忆）
│   ├── generation/       ← 多模态产出（图片、语音、音乐、SVG 渲染）
│   ├── tieba/            ← 贴吧爬虫与帖子池
│   ├── search/           ← 联网搜索后端
│   ├── sts/              ← 杀戮尖塔公式化回复（词表 + 公式）
│   └── common/           ← 限流、去重、持久化、消息缓冲
└── plugins/              ← NoneBot2 插件入口（re-export 薄层）
```

消息流：`bot.py` → `plugins`（NoneBot2 发现）→ `adapters/nonebot`（matcher 分发）→ `app`（管线装配）→ `chat` / `games` / `llm` 等子系统。

回复优先级从高到低：**复读 → 好女孩接龙 → 自定义接龙 → Session 游戏 → 彩蛋规则 → 语境规则 → 时区猜测 → STS card_le（链尾）**。每个环节受群级规则开关和滑动窗口限流保护。

目录约定：源码位于 `src/`（src layout），包路径 `quickquip.*` 不变；`src/plugins/` 是 NoneBot2 插件发现入口，只做 re-export；开发时需 `pip install -e .`（可编辑安装）。`config/` 下 `.example` 文件入版本控制，无后缀为部署私有配置。游戏参数集中在 `config/games.toml`。

详细结构见 [docs/dev/architecture.md](docs/dev/architecture.md)。

---

## 文档

| 文档 | 说明 |
|------|------|
| [docs/index.md](docs/index.md) | 文档总导航 |
| [docs/user/group-commands.md](docs/user/group-commands.md) | 群内指令速查 |
| [docs/user/private-commands.md](docs/user/private-commands.md) | 私聊指令速查 |
| [docs/admin/deployment.md](docs/admin/deployment.md) | 云端部署指南 |
| [docs/admin/configuration.md](docs/admin/configuration.md) | 完整配置参考 |
| [docs/admin/web-admin.md](docs/admin/web-admin.md) | Web 管理后台 |
| [docs/admin/sensitive-filter.md](docs/admin/sensitive-filter.md) | 敏感词过滤器 |
| [docs/admin/migration-napcat-to-llbot.md](docs/admin/migration-napcat-to-llbot.md) | NapCat 迁移 LLBot |
| [docs/dev/llm-module.md](docs/dev/llm-module.md) | LLM 模块详解 |
| [docs/dev/regex-tutorial.md](docs/dev/regex-tutorial.md) | 正则表达式教程 |
| [ROADMAP.md](ROADMAP.md) | 演进路线 |
| [CHANGELOG.md](CHANGELOG.md) | 变更记录 |

---

## 许可证

本项目基于 [WTFPL](LICENSE) 发布 — **Do What The F\*ck You Want To**。Copyright © 2026 [3aKHP](https://github.com/3aKHP)。

---

## 贡献

欢迎提交 Issue 和 Pull Request！添加新的回复规则只需编辑 `config/chat_rules.toml`（参见 `config/chat_rules.toml.example` 了解格式），无需改动消息管线本身。
