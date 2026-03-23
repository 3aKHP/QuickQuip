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
| `/llm trigger prefix_mode on|off` | 开关前缀触发 | 管理员/群主 |
| `/llm trigger at on|off` | 开关艾特触发 | 管理员/群主 |
| `/llm memory status` | 查看当前群记忆注入状态 | 所有人 |
| `/llm memory on|off` | 开关当前群记忆注入 | 管理员/群主 |
| `/llm clear_context` | 清空当前群的短期会话上下文 | 管理员/群主 |
| `/search <query>` | 使用当前搜索后端进行联网搜索 | 所有人 |
| `/search news <query>` | 使用当前搜索后端搜索新闻 | 所有人 |
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
│   └── llm.toml.example            # LLM 配置样例，复制为 llm.toml 后使用
├── docker/
│   └── searxng/
│       └── settings.yml            # 项目内置 SearXNG 配置
├── docker-compose.searxng.yml      # 项目内置 SearXNG 服务编排
├── .gitignore                      # Git 忽略规则
├── test_tz.py                      # 全功能断言测试脚本
├── test_llm.py                     # LLM 基础功能断言测试脚本
└── plugins/                        # 插件目录
    ├── llm_config.py               # LLM TOML 配置加载
    ├── llm_inputs.py               # 从消息段提取文本触发、艾特触发和图片 URL
    ├── llm_tools.py                # 统一工具调用数据结构
    ├── llm_tool_registry.py        # 工具注册表与参数校验
    ├── llm_mcp.py                  # MCP stdio/docker 客户端与工具桥接
    ├── llm_provider.py             # OpenAI / Claude / Gemini 协议适配
    ├── llm_runtime.py              # LLM 运行时入口、人格注入、上下文拼装
    ├── llm_store.py                # SQLite 持久化：群设置、短期会话、长期记忆
    ├── web_search.py               # 联网搜索后端抽象：SearXNG / Tavily
    ├── tavily_search.py            # 旧 Tavily 模块兼容导出层
    ├── tz_config.py                # 全局配置：关键词、时区映射、规则定义、限流参数
    ├── __init__.py                 # 包标记文件，便于测试和直接导入
    ├── tz_tracker.py               # 核心调度器：消息处理、回复分发、NoneBot 事件绑定
    ├── tz_utils.py                 # 时区工具函数：时差计算、地点格式化、候选时区查找
    ├── text_reply_rules.py         # 文字彩蛋规则引擎：正则匹配 + 模板渲染 + 随机回复
    ├── repeat_detector.py          # 复读检测器：群维度状态跟踪
    ├── rate_limit.py               # 滑动窗口限流器：全局 + 用户双层限流
    ├── good_girl_chain.py          # "好女孩"接龙状态机
    ├── message_stats.py            # 消息统计：按群跟踪消息量与规则触发
    ├── rule_switch.py              # 群级规则开关：按群禁用/启用规则
    └── scheduler.py                # 定时消息：基于 APScheduler 的 cron 任务
```

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

   复制 `config/llm.toml.example` 为 `config/llm.toml`，填入你的中转 URL、模型列表和默认人格。API Key 放进 [`.env`](.env)：

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

6. **启动机器人**

   ```bash
   python bot.py
   ```

### 运行测试

项目包含完整的断言测试，无需额外测试框架：

```bash
python test_tz.py
python test_llm.py
```

无输出即表示所有测试通过。脚本会打印部分回复示例供人工验证。

---

## ⚙️ 配置说明

规则相关配置集中在 [`plugins/tz_config.py`](plugins/tz_config.py) 中，可直接修改：

| 配置项 | 说明 | 默认值 |
|-------|------|--------|
| [`BEIJING_TIMEZONE`](plugins/tz_config.py:3) | 基准时区 | `Asia/Shanghai` |
| [`WAKE_TARGET`](plugins/tz_config.py:9) | 起床目标时间 | `07:30` |
| [`SLEEP_TARGET`](plugins/tz_config.py:10) | 睡觉目标时间 | `23:30` |
| [`WAKE_WORDS`](plugins/tz_config.py:6) | 起床触发词集合 | 起床、早安、醒了… |
| [`SLEEP_WORDS`](plugins/tz_config.py:7) | 睡觉触发词集合 | 晚安、睡觉、睡了… |
| [`RATE_LIMIT_WINDOW_SECONDS`](plugins/tz_config.py:12) | 限流滑动窗口大小 | `60` 秒 |
| [`RATE_LIMIT_RULES`](plugins/tz_config.py:13) | 各规则限流参数 | 见源码 |
| [`TEXT_REPLY_RULES`](plugins/tz_config.py:56) | 文字彩蛋规则列表 | 见源码 |
| [`SCHEDULED_MESSAGES`](plugins/tz_config.py) | 定时消息列表 | `[]`（空，休眠） |

LLM 相关配置放在 `config/llm.toml`：

| 配置区块 | 说明 |
|------|------|
| `[runtime]` | 默认 provider、人设、上下文长度、记忆条数 |
| `[triggers]` | 前缀触发、艾特触发、空提示回复 |
| `[tools]` | 标准化工具调用白名单 |
| `[mcp]` / `[[mcp.servers]]` | MCP 总开关、server 启动方式、白名单与 DOOD 相关参数 |
| `[[providers]]` | provider ID、协议类型、base URL、模型列表、默认参数 |
| `[[personas]]` | 人格卡、system prompt、风格注入 |

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

在 [`TEXT_REPLY_RULES`](plugins/tz_config.py:56) 列表中追加字典即可：

```python
{
    "name": "my_rule",                    # 规则唯一名称
    "patterns": [r"正则表达式"],            # 触发正则（支持多个）
    "reply_template": "回复模板",           # 支持 {sender_name}、{current_time}、$1 等
    "rate_limit_key": "my_rule",          # 限流 key（需在 RATE_LIMIT_RULES 中注册）
    "priority": 50,                       # 优先级（数字越大越优先）
}
```

**模板变量：**

| 变量 | 说明 |
|------|------|
| `{sender_name}` | 发送者昵称 |
| `{current_time}` | 当前北京时间（格式：`YYYY-MM-DD HH:MM`） |
| `{user_id}` | 发送者 QQ 号 |
| `$1`, `$2`, … | 正则捕获组 |
| `{命名捕获组}` | 正则命名捕获组（如 `(?P<target>...)` → `{target}`） |

**随机回复（可选）：** 将 `reply_template` 替换为 `reply_templates` 列表即可启用加权随机回复：

```python
{
    "name": "my_rule",
    "patterns": [r"正则表达式"],
    "reply_templates": [
        {"template": "回复A", "weight": 2},   # 出现概率较高
        {"template": "回复B", "weight": 1},
    ],
    "rate_limit_key": "my_rule",
    "priority": 50,
}
```

---

## 🏗️ 架构设计

```
群消息
  │
  ├─ stats_tracker.record_message()  ← 计入统计
  │
  ▼
tz_tracker.resolve_reply()           ← 统一入口
  │
  ├─① repeat_detector                ← 复读检测（最高优先）
  │
  ├─② good_girl_chain                ← 接龙会话
  │
  ├─③ text_reply_rules               ← 彩蛋规则匹配
  │
  └─④ build_timezone_reply()         ← 时区作息猜测（兜底）
  │
  ├─ rule_switch.is_enabled()        ← 群级开关过滤
  │
  ▼
rate_limiter.allow()                 ← 限流检查
  │
  ├─ stats_tracker.record_trigger()  ← 计入规则触发统计
  │
  ▼
发送回复 / 静默跳过
```

回复优先级从高到低：**复读 > 接龙 > 彩蛋规则 > 时区猜测**。每个环节均受群级规则开关控制，被禁用的规则会被跳过并尝试下一级。部分近义彩蛋规则会故意共享同一个限流桶，避免短时间内连续刷屏。每条回复在发送前都经过限流器检查。

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

下一阶段优先考虑的方向：

1. 保守版自动记忆抽取：仅从已经触发的 LLM 对话里提取高置信事实，不扫全天候群消息。
2. 更稳定的元数据与调试能力：让排查 prompt、联网判定和上下文污染更容易。
3. 自动联网能力：在独立开关下，让 AI 只在确实需要最新信息时才触发联网，并继续与长期记忆严格隔离。
4. 可插拔外部工具后端：在保留直连 API 的前提下，为部分能力预留 MCP 集成空间。

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！添加新的回复规则只需编辑 [`plugins/tz_config.py`](plugins/tz_config.py)，无需修改核心逻辑。
