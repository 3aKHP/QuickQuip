# QuickQuip 项目架构与结构

本文档记录整个仓库的目录与文件用途，以及"分发层"与"自用层"的划分原则。

---

## 核心概念：分发层 vs 自用层

| 层 | 含义 | 存储位置 |
|---|---|---|
| **分发层** | 可公开分发的通用代码与模板 | 追踪到 git（公共仓库可见） |
| **自用层** | 私有部署配置、个人数据、密钥 | gitignore 排除（不进入版本控制） |

凡是含有真实密钥、个人信息、群内私有内容的文件，均属自用层，必须 gitignore。

---

## 两种部署模式

| 模式 | 入口 | 环境变量来源 |
|---|---|---|
| 本地直接运行 | `pip install -e .` 后 `python bot.py` | 根目录 `.env` |
| 容器化部署 | `prod/` 私有部署编排 | 根目录 `.env` |

---

## 三层架构

QuickQuip 代码组织为三层结构：

1. **`src/quickquip/chat|common|llm|tieba|search|generation`** — 框架无关的业务逻辑
2. **`src/quickquip/adapters/nonebot/`** — NoneBot2 适配层（所有 matcher / command 注册在此）
3. **`src/plugins/`** — NoneBot2 插件发现入口，只做 re-export，不含业务逻辑

消息流顺序：

```
NoneBot2 event → tz_tracker_plugin matcher
                → group_messages.register_message_matcher (priority 60, block=False)
                → llm_service.generate_reply() [if LLM triggered]
                   or resolve_reply() [rule-based fallback]
```

规则回复链路：
1. `repeat_detector` — 复读/刷屏检测（最高优先级）
2. `good_girl_chain` / `custom_chain_games` — 接龙状态机（60s 超时）
3. `text_reply_rules` — 正则彩蛋匹配（优先级 + 加权随机）
4. `context_rules` — 语境感知规则（regex_context / llm_context 判定）
5. `build_timezone_reply()` — 时区猜测（兜底）
6. `rule_switch.is_enabled()` — 每步均受群级规则开关控制
7. `rate_limit.allow()` — 发送前限流检查
8. `stats_tracker` — 消息统计与规则触发计数

---

## 根目录

```
QuickQuip/
├── bot.py                  # NoneBot2 启动入口
├── web_api.py              # Web 管理后台入口（独立进程，监听 5104）
├── pyproject.toml          # 项目元数据与依赖声明
├── requirements.txt        # pip 安装用依赖列表
├── .env.example            # 本地部署环境变量模板
├── .env                    # 本地部署真实值（gitignore）
├── src/                    # Python 源码（src layout）
│   ├── quickquip/          # 业务逻辑包
│   └── plugins/            # NoneBot2 插件入口薄层
├── frontend/               # Web 管理后台前端（Vue 3 SPA）
│   ├── src/                # 源码
│   └── dist/               # 构建产物（gitignore）
├── docker-compose.example.yml  # Docker Compose 编排示例（含内置 SearXNG）
├── prod.example/          # 生产运维目录模板（追踪）
├── prod/                  # 真实生产运维目录（gitignore，由 prod.example/ 复制）
├── docker/
│   └── searxng/
│       └── settings.yml    # SearXNG 配置
├── CHANGELOG.md            # 模块级变更记录
├── ROADMAP.md              # 演进方向
└── README.md               # 项目入口与快速开始
```

---

## `src/quickquip/` — 业务逻辑包

项目采用 src layout，所有源码位于 `src/` 下。包导入路径 `quickquip.*` 保持不变。

```
src/quickquip/
├── chat/                    # 框架无关的聊天业务（时区猜测、复读、彩蛋规则、接龙、统计、规则开关、语境规则、每日总结/播报收集、节日检测）
├── common/                  # 通用工具（限流、持久化、消息去重、最近消息缓冲）
├── games/                   # 游戏模块（registry、scores、economy、config、各游戏实现）
├── llm/                     # LLM 运行时（多 provider、工具调用循环、MCP 客户端、记忆存储、persona、身份映射、词表、健康检查；核心门面拆到 service_parts/）
├── generation/              # 多模态产出配置、模型解析、图片/语音/音乐 provider 调用
├── tieba/                   # 贴吧爬虫与帖子池
├── search/                  # 项目内 SearXNG 搜索客户端
├── adapters/
│   └── nonebot/             # NoneBot2 适配层（生命周期、消息入口、命令注册、定时任务插件；命令注册按域拆到 command_parts/）
└── app/                     # 应用级流水线装配（单例初始化、状态加载、游戏注册）
    ├── web/                 # Web 管理后台 FastAPI 应用与路由
    │   └── routes/          # API 路由（统计、规则、群组、记忆、总结、对话、人格、资料、群LLM、配置、日志、限流、贴吧、词云、诊断、敏感词状态、MCP面板、定时任务、审计、金币经济、牛牛大作战）
```

**规则**：业务逻辑只进 `src/quickquip/`（包路径 `quickquip.*`），不进 `src/plugins/`。NoneBot2 相关 import 只在 `adapters/nonebot/` 里出现。

分层依赖方向、文件长度预警线、抽取触发条件、反模式与重构节奏等硬原则见 [`style.md`](style.md)。

---

## `src/plugins/` — NoneBot2 插件入口层

源码位于 `src/plugins/`。每个文件都是薄层 re-export，把 `quickquip.*` 里的对象暴露给 NoneBot2 插件发现机制。不含任何业务逻辑。

`bot.py` 通过 `nonebot.load_plugins(*plugins.__path__)` 加载已安装的 `plugins` 包路径。

---

## `config/` — 配置文件目录

| 文件 | 层 | 说明 |
|---|---|---|
| `llm.toml.example` | 分发层（追踪） | LLM provider / runtime / tools / MCP 配置模板 |
| `llm.toml` | 自用层（gitignore） | 真实 provider 配置，含 base_url / model 等 |
| `generation.toml.example` | 分发层（追踪） | 多模态产出配置模板 |
| `generation.toml` | 自用层（gitignore） | 真实图片/语音/音乐 provider 配置 |
| `awakening.toml.example` | 分发层（追踪） | 群聊唤醒模块配置模板 |
| `awakening.toml` | 自用层（gitignore） | 真实唤醒阈值、兴趣话题和按群覆盖 |
| `sensitive_words.toml.example` | 分发层（追踪） | 敏感词过滤器配置模板 |
| `sensitive_words.toml` | 自用层（gitignore） | 部署者填充的敏感词词表 |
| `chat_rules.toml.example` | 分发层（追踪） | 文字回复规则格式示例 |
| `chat_rules.toml` | 自用层（gitignore） | 部署专用的彩蛋规则（群内私有梗） |
| `games.toml.example` | 分发层（追踪） | 游戏参数配置模板 |
| `games.toml` | 自用层（gitignore） | 游戏参数（金币倍率、CD、赌注上限等） |
| `niuniu_text.toml.example` | 分发层（追踪） | 牛牛自定义文案模板 |
| `niuniu_text.toml` | 自用层（gitignore） | 部署者自定义牛牛文案 |
| `niuniu_text_safe.toml.example` | 分发层（追踪） | 牛牛和谐版文案模板 |
| `niuniu_text_safe.toml` | 自用层（gitignore） | 部署者自定义牛牛和谐版文案 |
| `personas.example/` | 分发层（追踪） | persona 配置格式示例 |
| `personas/` | 自用层（gitignore） | 真实 persona 定义（含人格描述、系统提示等） |

**原则**：永远只编辑 `.toml` / `personas/`，不编辑 `.example`。`.example` 只在格式需要变更时更新。

---

## `data/` — 运行时持久化数据（自用层，gitignore）

```
data/
├── stats.json              # 群消息统计
├── rule_switch.json        # 群规则开关状态
├── llm.db                  # LLM 对话历史与长期记忆（SQLite）
├── daily_summaries.db      # 每日群聊总结存档（SQLite）
├── web_admin_sessions.db   # Web Admin 会话记录
├── web_admin_actions.db    # Web Admin 到 bot 进程的动作队列
├── awakening_boredom_groups.json # 已启用无聊唤醒的群列表
├── daily_msgs/             # 每日消息原始收集（{group_id}/{date}.jsonl）
├── logs/                   # loguru 文件日志（保留 14 天）+ 共享 LLM trace JSONL
├── fonts/                  # 词云字体文件（手动放置）
├── tieba/
│   ├── pool.json           # 贴吧帖子池
│   └── storage_state.json  # 贴吧登录态（Playwright 导出）
└── searxng/                # SearXNG 缓存
```

---

## `docs/` — 面向用户的公开文档（分发层）

```
docs/
├── index.md                # 文档总导航
├── user/                   # 面向群友
│   ├── group-commands.md
│   ├── group-games.md
│   ├── llm-tool-discovery.md
│   ├── private-commands.md
│   └── three-kingdoms-memes.md
├── admin/                  # 面向部署者/管理员
│   ├── deployment.md
│   ├── configuration.md
│   ├── game-config.md
│   ├── migration-napcat-to-llbot.md
│   ├── sensitive-filter.md
│   ├── tool-discovery.md
│   └── web-admin.md
└── dev/                    # 面向开发者
```

---

## 私有部署材料

真实部署脚本配置、运维通知密钥、compose 运行态目录和临时分析材料均属自用层，不属于公共仓库分发内容。公共文档只记录通用配置格式和运行方式，不记录个人生产目录结构。

### `prod.example/` 与 `prod/`

- `prod.example/`：可公开分发的生产运维模板，包含 compose、Dockerfile、部署脚本、巡检脚本和示例通知配置。
- `prod/`：由 `prod.example/` 复制得到的真实生产运维目录，进入 `.gitignore`，可保存服务器专用脚本配置、LLBot 登录态目录和运维通知密钥。
- 本地私有工作区只用于草稿、测试沙箱、探针脚本和工作文档，不承担生产环境变量覆盖职责。

### 私有环境变量与根 `.env` 的关系

- **根 `.env`**：QuickQuip 应用唯一的涉密环境变量来源，供本地运行与 `prod/` 容器部署共同读取，必须保持 gitignore。
- **`prod/sendkey.env`**：可选运维通知密钥，仅由巡检脚本读取，不被 QuickQuip 应用加载。
- 本地私有工作区只用于草稿、测试沙箱、探针脚本和工作文档。

### `llm_about` 部署路径

`llm_about/` 是 vocab.yaml 和 identities.yaml 的唯一生产部署路径。Docker 部署时应把仓库根目录的 `llm_about/` 挂载进容器：

- 宿主机 `llm_about/` → 容器内 `/app/llm_about/`

历史私有资料路径已弃用，不应再被 compose 挂载或由部署脚本读写。

---

## `.gitignore` 排除规则摘要

| 路径 | 原因 |
|---|---|
| `.env`, `.env.*` | 含真实密钥（`.env.example` 除外） |
| `config/llm.toml` | 含真实 provider 配置 |
| `config/llm.*.local.toml` | 同上 |
| `config/generation.toml` | 含真实多模态 provider 配置 |
| `config/awakening.toml` | 含真实唤醒阈值、兴趣话题和群覆盖 |
| `config/sensitive_words.toml` | 含部署者填充的敏感词词表 |
| `config/chat_rules.toml` | 含私有群梗规则 |
| `config/games.toml` | 含游戏参数配置 |
| `config/niuniu_text.toml`, `config/niuniu_text_safe.toml` | 含部署者自定义牛牛文案 |
| `config/personas/` | 含真实 persona 定义 |
| `data/` | 运行时数据 |
| `prod/` | 真实生产运维目录、运行态目录和运维密钥 |
| 本地私有工作区 | 本地开发草稿、沙箱、探针脚本和工作文档 |
