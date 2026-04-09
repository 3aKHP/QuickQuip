# QuickQuip — QQ 群聊妙语机器人 🤖💬

> 基于 [NoneBot2](https://nonebot.dev/) + [OneBot V11](https://github.com/nonebot/adapter-onebot) 的 QQ 群聊互动机器人，用妙语让群聊更有趣。

QuickQuip（双 Q 谐音 = QQ + Quip/妙语）是一个**轻量级、规则驱动优先**的 QQ 群聊机器人。它原本不依赖大模型，通过精心设计的正则匹配和状态机，在群聊中自动给出有趣的回复。现在项目也支持按群启用 LLM 扩展，显式通过指令或艾特触发对话，并可切换不同 provider 和 model。

---

## ✨ 功能一览

### 🌍 时区作息猜测

当群友发送「早安」「晚安」等作息关键词时，机器人会根据当前北京时间反推全球最匹配的时区，幽默地"揭穿"你的真实所在地。

**触发词：** `起床` `早安` `醒了` `睡醒了` `起了` `苏醒` `晚安` `睡觉` `睡了` `睡啦` `困了` `眠了`

**回复示例：**
```
现在是北京时间2026-03-16 09:19，位于上海的@某某 要起床了。TA也有可能在东京或首尔。
```

### 🔁 复读检测

机器人会观察群内复读行为，并做出不同反应：

| 场景 | 行为 |
|------|------|
| **不同人**连续发送相同消息（第 2 条） | 跟读该消息 |
| **同一人**连续发送相同消息（第 2 条） | 复读但删掉最后一个字 |
| **同一人**连续刷屏（第 4 条） | @该用户 并发出警告 |

### 🎭 文字彩蛋规则

内置多条基于正则匹配的趣味回复规则，支持优先级排序：

| 规则名称 | 触发示例 | 回复示例 | 优先级 |
|---------|---------|---------|--------|
| `master_protection` | 四区 / 4区 | 你不许说他他是我跌 | `PRIORITY_ABSOLUTE` |
| `kpl_final` | A尽力，B犯罪，C的XX不团队 | 我说A才是最大的一条区有没有懂的 | 200 |
| `divine_arrival` | 神临 / 降临 | {时间}，@{昵称} 区从天降 | 100 |
| `maggot_arrival` | 区临 / 区来了 | {时间}，有自知之明的@{昵称} 区从天降 | 95 |
| `genshin_start` | 原神，启动！ | 该启动原神了，少爷 | 90 |
| `play_target` | 玩XX玩的 | XX怎么你了 | 85 |
| `double_char_ni_de` | 牛牛你的 | 牛牛魔 | 80 |
| `sandwich_de` | 冰红茶冰的 | 红茶怎么你了！ | 75 |
| `like_reply` | 我喜欢XX / 喜欢XX | 还在XX | 60 |
| `huaizhen_oversize` | 怀真 / 赵怀真 | 赵怀真还不超标啊 | 50 |
| `i_do` | 我XX（过滤常见口语） | 不准XX | 20 |

### 🔗 "好女孩"接龙

当有人发送 `XX是好XX吗？` 格式的消息时，机器人会启动接龙会话，逐字回复 `别 → 逗 → 你 → {首字} → 姐 → 笑 → 了 → 🤣`，群友可以参与接力完成整条链。会话有 60 秒超时保护。

**示例：**
```
用户：   小明是好学生吗？
机器人： 别
用户：   逗
机器人： 你
用户：   小
机器人： 姐
...
机器人： 🤣
```

### 📊 消息统计

机器人会自动统计每个群的消息数量和规则触发次数，可通过命令查看。

| 命令 | 说明 | 权限 |
|------|------|------|
| `/stats` | 查看当前群的消息统计 | 所有人 |
| `/reset_stats` | 重置当前群的统计数据 | 管理员/群主 |

**回复示例：**
```
群聊统计
消息总数：1234
活跃用户 Top 5：
  1. 张三 — 200 条
  2. 李四 — 150 条
规则触发 Top 5：
  1. repeat_follow_read — 50 次
  2. divine_arrival — 30 次
```

### 🔧 群级规则开关

管理员可以按群禁用或启用任意规则，实现精细化管控。

| 命令 | 说明 | 权限 |
|------|------|------|
| `/disable <rule_name>` | 在本群禁用指定规则 | 管理员/群主 |
| `/enable <rule_name>` | 在本群启用指定规则 | 管理员/群主 |
| `/rules` | 查看所有规则及其开关状态 | 所有人 |

### 🧠 LLM 扩展

支持通过配置文件接入兼容 OpenAI、Claude、Gemini 三种协议的接口，并按群动态切换模型。

| 命令 | 说明 | 权限 |
|------|------|------|
| `/llm status` | 查看当前群 LLM 状态 | 所有人 |
| `/llm current` | 查看当前群 LLM 运行配置与上下文/记忆计数 | 所有人 |
| `/llm on` / `/llm off` | 开关当前群 LLM | 管理员/群主 |
| `/llm providers` | 查看可用 provider | 所有人 |
| `/llm models [provider]` | 查看模型列表 | 所有人 |
| `/llm use <provider> <model>` | 切换当前群使用的 provider 和模型 | 管理员/群主 |
| `/llm personas` | 查看可用人格 | 所有人 |
| `/llm persona use <id>` | 切换当前群人格 | 管理员/群主 |
| `/llm trigger prefix <value>` | 设置显式触发前缀 | 管理员/群主 |
| `/llm trigger prefix_mode on\|off` | 开关前缀触发 | 管理员/群主 |
| `/llm trigger at on\|off` | 开关艾特触发 | 管理员/群主 |
| `/llm memory status` | 查看当前群记忆注入状态 | 所有人 |
| `/llm memory on\|off` | 开关当前群记忆注入 | 管理员/群主 |
| `/llm clear_context` | 清空当前群的短期会话上下文 | 管理员/群主 |
| `/search <query>` | 使用当前搜索后端进行联网搜索 | 所有人 |
| `/search news <query>` | 使用当前搜索后端搜索新闻 | 所有人 |
| `/defectify [内容]` | 把文字/图片/引用消息转写成近音“故障机器人”的五字别名 | 所有人 |
| `/remember <内容>` | 手工写入群记忆 | 管理员/群主 |
| `/memories [关键词]` | 查看当前群记忆 | 所有人 |
| `/forget <关键词>` | 删除匹配的群记忆 | 管理员/群主 |

默认只在以下场景触发 LLM：

- 消息以 `/ai` 之类的配置前缀开头
- 消息中 `@机器人`

当前版本还支持在显式触发时附带图片：

- `/ai` + 图片
- `@机器人` + 图片

未附带文字提示时，会自动按“请描述这张图片”处理。

当前实现还额外遵循两条硬约束：

- 每次 LLM 响应只会看到触发当下往前最多 20 条群消息，这部分仅保存在内存中，不做长期持久化
- LLM 的短期会话记录和长期记忆都有硬上限，不会无限增长

当前版本还支持标准化工具调用，并可桥接到 MCP server：

- `get_identity`：查询标准身份词表
- `list_memories`：查询当前群长期记忆
- `search_web`：通过当前搜索后端进行联网搜索

工具调用仍然只发生在显式触发的 LLM 对话内部，不会扩展到普通规则消息流。

当前版本还支持私聊 LLM：

- 私聊默认不会自动进入 LLM，需要先发送 `/start_sesssion` 开启会话；`/end_session` 用于结束当前会话
- 会话开启后，普通文本、图片和引用回复都会进入 LLM；已注册的斜杠命令仍然优先走命令处理
- 私聊沿用当前可用的人格列表，但会在提示词里自动收敛成更适合一对一聊天的表达方式
- 私聊单会话的默认上下文上限为 256 条，适合连续对话
- 私聊可继续使用 `/llm status`、`/llm current`、`/llm persona use <id>`、`/llm trigger prefix <value>`、`/llm context_limit <n>`、`/llm clear_context`、`/search`、`/remember`、`/memories`、`/forget`、`/forget_all`
- 私聊中 `/defectify` 与 `/故障化` 仍可单独使用，不依赖当前会话是否开启

### 🤖 故障机器人转写

支持把任意有意义的文字、图片，或显式引用的一条消息，转写成一个读音贴近“故障机器人”的五字别名。该功能走专门的 LLM 约束 prompt，会尽量保证每个字都能回扣到输入语义，并固定输出：

```text
某某某某某
笑点解析：......。令人忍俊不禁。
```

### 📰 每日群聊总结

每天凌晨 06:00 自动收集前一个 06:00–06:00 窗口的群聊记录，调用 LLM 以 persona 口吻生成约 2000 字小作文，并在中午 12:00 定时发布到群里。支持模型级联策略（失败自动降级），注入群成员昵称对照表，消息量不足时自动跳过。

| 命令 | 说明 | 权限 |
|------|------|------|
| `/summary on` | 开启本群每日总结 | 管理员/群主 |
| `/summary off` | 关闭本群每日总结 | 管理员/群主 |
| `/summary status` | 查看本群每日总结开关状态 | 所有人 |
| `/summary now` | 立即生成前一天 06:00 至当前时刻的总结（每分钟限一次） | 管理员/群主 |

每日总结默认全局关闭，需在群内执行 `/summary on` 后才会为该群启用消息收集与定时生成。生成与发布时间可在 `config/llm.toml` 的 `[daily_summary]` 区块中自定义。

### 🖼️ 多贴吧随机搬运

支持为多个贴吧分别维护本地帖子池，并在群里随机抽取一条帖子发送，也支持按指定来源搬运。

| 命令 | 说明 | 权限 |
|------|------|------|
| `/tieba [贴吧名]` | 随机发送一条缓存帖子，默认带镇楼图；可指定来源贴吧 | 所有人 |
| `/tieba text [贴吧名]` | 随机发送一条缓存帖子，仅文字；可指定来源贴吧 | 所有人 |
| `/tieba status [贴吧名]` | 查看全部或指定贴吧的缓存、同步和登录态状态 | 所有人 |
| `/tieba source [贴吧名]` | 查看全部或指定贴吧的来源池摘要 | 所有人 |
| `/tieba refresh [贴吧名\|all]` | 立即同步全部或指定贴吧 | 管理员/群主 |

当前实现会优先读取 `.env` 中的 `TIEBA_FORUM_KEYWORDS` 作为多贴吧来源列表；如果未配置，则回退到旧版单贴吧配置 `TIEBA_FORUM_KEYWORD`。登录后的跨平台 `storage_state.json` 保存在 `data/tieba/` 下，各贴吧来源共用同一份登录态。遇到百度安全验证时，需要人工运行登录辅助脚本续签，不会自动绕过验证。

### 🎲 随机回复（引擎已就绪）

规则支持配置 `reply_templates` 加权随机列表，同一条规则命中后可随机选择不同回复，避免机械感。当前所有规则仅使用单模板，待后续配置启用。

### ⏰ 定时消息（引擎已就绪）

支持通过 `SCHEDULED_MESSAGES` 配置 cron 定时向指定群发送消息（如每日问候、节日祝福）。当前配置为空，待后续启用。

### 🚦 频率限制

所有回复均受**滑动窗口限流**保护（默认 60 秒窗口），每条规则独立配置全局上限和单用户上限，防止刷屏：

| 规则 | 全局上限 | 单用户上限 |
|------|---------|-----------|
| 时区作息回复 | 3 次/分钟 | 1 次/分钟 |
| 彩蛋规则 | 6 次/分钟 | 3 次/分钟 |
| 复读跟读 | 8 次/分钟 | 3 次/分钟 |
| 接龙回复 | 20 次/分钟 | 10 次/分钟 |

---

## 📁 项目结构

```
QuickQuip/
├── bot.py                          # NoneBot2 入口，注册适配器并加载插件
├── .env                            # 环境变量配置（不纳入版本控制）
├── config/
│   ├── llm.toml.example            # LLM 配置样例，复制为 llm.toml 后使用
│   ├── chat_rules.toml.example     # 文字回复规则样例，复制为 chat_rules.toml 后使用
│   └── personas.example/           # 人格定义样例目录，复制为 personas/ 后使用
├── docker/
│   └── searxng/
│       └── settings.yml            # 项目内置 SearXNG 配置
├── docker-compose.searxng.yml      # 项目内置 SearXNG 服务编排
├── quickquip/                      # 主代码目录
│   ├── adapters/nonebot/           # NoneBot 生命周期、消息入口与命令注册
│   ├── app/                        # 应用级消息管线与状态装配
│   ├── chat/                       # 规则驱动聊天能力：时区、复读、接龙、统计、规则开关
│   ├── common/                     # 通用基础设施：JSON 持久化、限流、去重、最近消息缓冲
│   ├── llm/                        # LLM 配置、运行时组件、provider、MCP、工具调用
│   ├── search/                     # 联网搜索后端与兼容导出
│   └── tieba/                      # 多贴吧配置、抓取、缓存与服务层
├── .gitignore                      # Git 忽略规则
├── test_tz.py                      # 全功能断言测试脚本
├── test_llm.py                     # LLM 基础功能断言测试脚本
└── plugins/                        # NoneBot2 插件入口层（薄层 re-export，不含业务逻辑）
    ├── tz_tracker.py               # → quickquip.adapters.nonebot.tz_tracker_plugin
    ├── llm_runtime.py              # → quickquip.llm.service
    └── ...                         # 其余文件均为对应 quickquip.* 子包的 re-export
```

目录约定：`quickquip/` 承载全部实现（业务逻辑在 `chat|common|llm|tieba|search`，NoneBot2 适配在 `adapters/nonebot/`）；`plugins/` 是 NoneBot2 插件发现的入口目录，只做 re-export 不写逻辑；`config/` 下以 `.example` 结尾的文件入版本控制，无后缀的为部署私有配置（gitignored）。

---

## 🚀 快速开始

### 环境要求

- **Python** ≥ 3.11（使用了 `X | Y` 类型联合语法和 `zoneinfo` 模块）
- **NoneBot2** + **OneBot V11 适配器**
- OneBot V11 协议实现端（如 [Lagrange.OneBot](https://github.com/LagrangeDev/Lagrange.Core)、[NapCat](https://github.com/NapNeko/NapCatQQ) 等）

### 安装步骤

1. **克隆仓库**

   ```bash
   git clone https://github.com/3aKHP/QuickQuip.git QuickQuip
   cd QuickQuip
   ```

2. **创建虚拟环境并安装依赖**

   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # Linux / macOS
   source .venv/bin/activate

   pip install -r requirements.txt
   ```

3. **配置环境变量**

   在项目根目录创建 [`.env`](.env) 文件，参考 NoneBot2 文档配置连接参数：

   ```env
   DRIVER=~fastapi
   HOST=0.0.0.0
   PORT=8080
   SEARCH_BACKEND=auto
   SEARXNG_BASE_URL=http://127.0.0.1:8888
   ```

4. **可选：启动项目内置 SearXNG**

   项目已经附带一份 SearXNG 配置，可直接在仓库根目录启动：

   ```bash
   docker compose -f docker-compose.searxng.yml up -d
   ```

   默认会把 SearXNG 暴露到 `http://127.0.0.1:8888`，并允许 JSON 搜索接口，供 `/search` 命令和 LLM 内部 `search_web` 工具直接复用。

5. **可选：启用 LLM**

   复制 `config/llm.toml.example` 为 `config/llm.toml`，复制 `config/personas.example/` 目录为 `config/personas/`，填入你的中转 URL、模型列表和人格定义。API Key 放进 [`.env`](.env)：

   ```env
   OPENAI_API_KEY=your_openai_key_here
   ANTHROPIC_API_KEY=your_claude_key_here
   GEMINI_API_KEY=your_gemini_key_here
   DEEPSEEK_API_KEY=your_deepseek_key_here
   GITHUB_PERSONAL_ACCESS_TOKEN=your_github_pat_here
   GITHUB_TOOLSETS=context,repos,issues,pull_requests,users,actions
   GITHUB_READ_ONLY=
   MCP_ARXIV_PAPERS_MOUNT=arxiv-papers:/root/.arxiv-mcp-server/papers
   MCP_PRTS_WIKI_ENABLED=false
   MCP_PRTS_GAMEDATA_MOUNT=/absolute/path/to/ArknightsGameData:/data/gamedata:ro
   MCP_PRTS_STORYJSON_MOUNT=/absolute/path/to/ArknightsStoryJson:/data/storyjson:ro
   ```

   如需保留 Tavily 作为备用搜索后端，可额外配置：

   ```env
   TAVILY_API_KEY=your_tavily_key_here
   ```

6. **可选：启用多贴吧随机搬运**

   安装 Playwright 依赖后，还需要安装浏览器：

   ```bash
   python -m playwright install chromium
   ```

   然后在 [`.env`](.env) 中配置贴吧来源：

   ```env
   TIEBA_ENABLED=true
   TIEBA_FORUM_KEYWORDS=示例贴吧名1,示例贴吧名2
   TIEBA_SYNC_INTERVAL_SECONDS=900
   TIEBA_BROWSER_HEADLESS=true
   ```

   `TIEBA_FORUM_KEYWORDS` 支持用逗号、分号、竖线或换行分隔多个贴吧名，例如 `搬石,明日方舟手游`。如果仍然只想配置一个来源，也可以继续使用旧字段 `TIEBA_FORUM_KEYWORD`。当前实现会自动兼容末尾多写一个 `吧` 的情况。

   首次使用前，运行登录辅助脚本，在弹出的浏览器里手动完成贴吧登录和任何安全验证：

   ```bash
   python dev/tools/tieba_login.py
   ```

7. **启动机器人**

   ```bash
   python bot.py
   ```

### 运行测试

项目包含完整的断言测试，无需额外测试框架：

```bash
python test_tz.py
python test_llm.py
python test_tieba.py
```

无输出即表示所有测试通过。脚本会打印部分回复示例供人工验证。

---

## ⚙️ 配置说明

规则相关配置分为两部分：

**基础参数**（修改 `quickquip/chat/config.py`）：

| 配置项 | 说明 | 默认值 |
|-------|------|--------|
| `BEIJING_TIMEZONE` | 基准时区 | `Asia/Shanghai` |
| `WAKE_TARGET` | 起床目标时间 | `07:30` |
| `SLEEP_TARGET` | 睡觉目标时间 | `23:30` |
| `WAKE_WORDS` | 起床触发词集合 | 起床、早安、醒了… |
| `SLEEP_WORDS` | 睡觉触发词集合 | 晚安、睡觉、睡了… |
| `RATE_LIMIT_WINDOW_SECONDS` | 限流滑动窗口大小 | `60` 秒 |
| `SCHEDULED_MESSAGES` | 定时消息列表 | `[]`（空，休眠） |

**文字回复规则**（编辑 `config/chat_rules.toml`，参见 `config/chat_rules.toml.example`）：

| 配置项 | 说明 |
|-------|------|
| `[rate_limit_rules]` | 文字规则专用限流桶（桶名 + 全局/用户上限） |
| `[[rules]]` | 回复规则列表（触发正则、优先级、回复模板、限流桶） |

LLM 相关配置放在 `config/llm.toml` 和 `config/personas/` 目录：

| 配置区块 | 文件 | 说明 |
|------|------|------|
| `[runtime]` | `llm.toml` | 默认 provider、人设、上下文长度、记忆条数 |
| `[triggers]` | `llm.toml` | 前缀触发、艾特触发、空提示回复 |
| `[tools]` | `llm.toml` | 标准化工具调用白名单 |
| `[mcp]` / `[[mcp.servers]]` | `llm.toml` | MCP 总开关、server 启动方式、白名单与 DOOD 相关参数 |
| `[daily_summary]` | `llm.toml` | 每日总结全局开关、生成/发布 cron、最小消息数、字数目标、模型级联列表 |
| `[[providers]]` | `llm.toml` | provider ID、协议类型、base URL、模型列表、默认参数 |
| `_shared.toml` | `personas/` | 自动注入所有人格的共享行为准则与风格规则 |
| `<id>.toml` | `personas/` | 单个人格卡：id、display_name、system_prompt、style_prompt + 自由扩展字段 |

联网搜索后端通过 `.env` 中的 `SEARCH_BACKEND` 控制：

- `auto`：若设置了 `SEARXNG_BASE_URL`，优先使用 SearXNG；否则使用 Tavily
- `searxng`：固定使用 SearXNG
- `tavily`：固定使用 Tavily

项目附带的 `docker-compose.searxng.yml` 会把 SearXNG 作为本地服务启动，并通过 `docker/searxng/settings.yml` 开启 `json` 输出格式，供机器人直接调用。

### MCP 配置要点

- `LLMService` 会在启动时初始化已启用的 MCP server，并在 `/llm reload` 时重新装载。
- `transport = "stdio"` 适合本机命令或脚本。
- `transport = "docker"` 适合云端部署时按需拉起 sibling container，`command` 层走 Docker CLI，便于配合 DOOD。
- `mount_docker_socket = true` 时，会自动附加 `/var/run/docker.sock:/var/run/docker.sock` 挂载，适合需要访问宿主 Docker daemon 的 MCP server。
- `mounts`、`docker_args`、`env` 可以继续补充工作目录、卷挂载、网络和环境变量。
- 配置值支持 `${ENV_VAR}` 与 `${ENV_VAR:-default}`，适合把本机和云端的密钥、卷挂载和开关留在 `.env` / `dev/.env`。
- 当前项目默认把 GitHub、Tavily、arXiv、PRTS Wiki 作为可选 MCP server 放在 `config/llm.toml` 中，PRTS Wiki 建议在云端通过 `MCP_PRTS_WIKI_ENABLED=false` 单独关闭或改成云端可用挂载。
- 当 `[tools].enabled = []` 时，运行时会自动暴露内建工具和已发现的 MCP 工具；若填写白名单，则按工具名精确过滤。

### 添加自定义回复规则

在 `config/chat_rules.toml` 中追加 `[[rules]]` 条目即可（参见 `config/chat_rules.toml.example`）：

```toml
[rate_limit_rules]
my_rule = {global_limit = 6, user_limit = 3}   # 注册限流桶

[[rules]]
name           = 'my_rule'          # 规则唯一名称
patterns       = ['正则表达式']      # 触发正则（支持多条，用单引号避免反斜杠被转义）
reply_template = '回复模板'          # 支持 {sender_name}、{current_time}、$1 等
rate_limit_key = 'my_rule'          # 使用的限流桶
priority       = 50                  # 优先级（数字越大越优先）
```

**模板变量：**

| 变量 | 说明 |
|------|------|
| `{sender_name}` | 发送者昵称 |
| `{current_time}` | 当前北京时间（格式：`YYYY-MM-DD HH:MM`） |
| `{user_id}` | 发送者 QQ 号 |
| `$1`, `$2`, … | 正则捕获组 |
| `{命名捕获组}` | 正则命名捕获组（如 `(?P<target>...)` → `{target}`） |

**随机回复（可选）：** 将 `reply_template` 替换为 `[[rules.reply_templates]]` 列表：

```toml
[[rules]]
name           = 'my_rule'
patterns       = ['正则表达式']
rate_limit_key = 'my_rule'
priority       = 50

[[rules.reply_templates]]
template = '回复A'
weight   = 2

[[rules.reply_templates]]
template = '回复B'
weight   = 1
```

---

## 🏗️ 架构设计

```
bot.py
  │
  ▼
plugins/tz_tracker.py                    ← NoneBot2 插件入口（re-export 薄层）
  │
  ▼
quickquip/adapters/nonebot/
  ├─ lifecycle.py                        ← 启动、关停、定时保存
  ├─ group_messages.py                   ← 群消息入口
  ├─ private_messages.py                 ← 私聊消息入口
  ├─ daily_summary_plugin.py             ← 每日总结定时任务与 /summary 命令
  └─ commands.py                         ← /llm /stats /tieba 等命令注册
  │
  ▼
quickquip/app/message_pipeline.py        ← 应用级消息管线与共享状态装配
  │
  ├─ quickquip/chat/repeat_detector.py   ← 复读检测
  ├─ quickquip/chat/good_girl_chain.py   ← 接龙会话
  ├─ quickquip/chat/text_rules.py        ← 彩蛋规则
  ├─ quickquip/chat/timezones.py         ← 时区候选与地点格式化
  ├─ quickquip/chat/rule_switch.py       ← 群级规则开关
  ├─ quickquip/chat/message_stats.py     ← 群消息统计
  ├─ quickquip/chat/daily_summary.py     ← 消息收集器、总结 SQLite 存储、群开关
  └─ quickquip/common/                   ← 限流、去重、最近消息缓冲、JSON 持久化
  │
  ├─ quickquip/llm/                      ← LLM 配置、provider、MCP、tool loop、prompt 构建
  ├─ quickquip/llm/summarize.py          ← 每日总结生成（模型级联、截断、prompt 构建）
  ├─ quickquip/search/                   ← SearXNG / Tavily 搜索后端
  └─ quickquip/tieba/                    ← 多贴吧配置、抓取、缓存与服务层
```

普通规则消息的回复优先级从高到低仍然是：**复读 > 接龙 > 彩蛋规则 > 时区猜测**。每个环节均受群级规则开关控制，被禁用的规则会被跳过并尝试下一级。部分近义彩蛋规则会共享同一个限流桶，避免短时间内连续刷屏。每条回复在发送前都经过限流器检查。

LLM、贴吧与联网搜索能力在目录上已经独立成子系统，便于后续继续细分 provider、存储、抓取器和工具桥接实现。每日总结单独维护消息收集层与 SQLite 摘要存储，与主会话上下文完全隔离。

---

## 📄 许可证

本项目基于 [WTFPL](LICENSE) 发布 — **Do What The F\*ck You Want To**。想干嘛就干嘛。Copyright © 2026 [3aKHP](https://github.com/3aKHP)。

---

## 🛣️ 后续规划

当前阶段已经完成：

- 显式触发的 LLM 对话
- 群级 provider / model / persona 切换
- 人格注入与词表注入
- 手动长期记忆
- 严格限制的短期上下文
- 图片识别
- 可切换联网搜索后端（内置 SearXNG / Tavily）
- 每日群聊总结（定时生成 + 发布，模型级联，群级开关）

下一阶段优先考虑的方向：

1. 保守版自动记忆抽取：仅从已经触发的 LLM 对话里提取高置信事实，不扫全天候群消息。
2. 更稳定的元数据与调试能力：让排查 prompt、联网判定和上下文污染更容易。
3. 自动联网能力：在独立开关下，让 AI 只在确实需要最新信息时才触发联网，并继续与长期记忆严格隔离。
4. 可插拔外部工具后端：在保留直连 API 的前提下，为部分能力预留 MCP 集成空间。

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！添加新的回复规则只需编辑 `config/chat_rules.toml`（参见 [`config/chat_rules.toml.example`](config/chat_rules.toml.example) 了解格式），无需改动消息管线本身。
