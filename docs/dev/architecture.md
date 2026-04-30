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
| 本地直接运行 | `python bot.py` | 根目录 `.env` |
| **云端 Docker（主用）** | `cd dev && docker compose up -d` | `dev/.env`（唯一来源） |

---

## 三层架构

QuickQuip 代码组织为三层结构：

1. **`quickquip/chat|common|llm|tieba|search|generation`** — 框架无关的业务逻辑
2. **`quickquip/adapters/nonebot/`** — NoneBot2 适配层（所有 matcher / command 注册在此）
3. **`plugins/`** — NoneBot2 插件发现入口，只做 re-export，不含业务逻辑

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
├── frontend/               # Web 管理后台前端（Vue 3 SPA）
│   ├── src/                # 源码
│   └── dist/               # 构建产物（gitignore）
├── docker-compose.searxng.yml  # 项目内置 SearXNG 服务编排
├── docker/
│   └── searxng/
│       └── settings.yml    # SearXNG 配置
├── CHANGELOG.md            # 模块级变更记录
├── ROADMAP.md              # 演进方向
└── README.md               # 项目入口与快速开始
```

---

## `quickquip/` — 业务逻辑包（分发层）

```
quickquip/
├── chat/                    # 框架无关的聊天业务（时区猜测、复读、彩蛋规则、接龙、统计、规则开关、语境规则、每日总结/播报收集）
├── common/                  # 通用工具（限流、持久化、消息去重、最近消息缓冲）
├── llm/                     # LLM 运行时（多 provider、工具调用循环、MCP 客户端、记忆存储、persona、身份映射、词表、健康检查）
├── generation/              # 多模态产出配置、模型解析、图片/语音/音乐 provider 调用
├── tieba/                   # 贴吧爬虫与帖子池
├── search/                  # 联网搜索后端（SearXNG / Tavily）
├── adapters/
│   └── nonebot/             # NoneBot2 适配层（生命周期、消息入口、命令注册、定时任务插件）
└── app/                     # 应用级流水线装配（单例初始化、状态加载）
    └── web/                 # Web 管理后台 FastAPI 应用与路由
```

**规则**：业务逻辑只进 `quickquip/`，不进 `plugins/`。NoneBot2 相关 import 只在 `adapters/nonebot/` 里出现。

---

## `plugins/` — NoneBot2 插件入口层（分发层）

每个文件都是薄层 re-export，把 `quickquip.*` 里的对象暴露给 NoneBot2 插件发现机制。不含任何业务逻辑。

---

## `config/` — 配置文件目录

| 文件 | 层 | 说明 |
|---|---|---|
| `llm.toml.example` | 分发层（追踪） | LLM provider / runtime / tools / MCP 配置模板 |
| `llm.toml` | 自用层（gitignore） | 真实 provider 配置，含 base_url / model 等 |
| `generation.toml.example` | 分发层（追踪） | 多模态产出配置模板 |
| `generation.toml` | 自用层（gitignore） | 真实图片/语音/音乐 provider 配置 |
| `chat_rules.toml.example` | 分发层（追踪） | 文字回复规则格式示例 |
| `chat_rules.toml` | 自用层（gitignore） | 部署专用的彩蛋规则（群内私有梗） |
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
├── daily_msgs/             # 每日消息原始收集（{group_id}/{date}.jsonl）
├── logs/                   # loguru 文件日志（保留 14 天）
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
│   ├── private-commands.md
│   └── three-kingdoms-memes.md
├── admin/                  # 面向部署者/管理员
│   ├── deployment.md
│   ├── configuration.md
│   └── web-admin.md
└── dev/                    # 面向开发者
    ├── architecture.md     # 本文件
    ├── llm-module.md
    ├── mcp-integration.md
    └── regex-tutorial.md
```

---

## `dev/` — 私有部署工具目录（自用层，整体 gitignore）

```
dev/
├── .env.deploy             # 云端部署环境变量模板
├── .env                    # 云端部署真实值
├── Dockerfile              # 容器镜像构建文件
├── docker-compose.yml      # 服务编排（quickquip + napcat + searxng + web-admin）
├── deploy.sh               # Linux 一键部署脚本
├── deploy.ps1              # Windows 一键部署脚本（旧）
├── deploy-v4.ps1           # Windows 一键部署脚本（新）
├── llm_about/
│   ├── identities.yaml     # 群友 QQ 号 → 标准身份映射（私有）
│   ├── vocab.yaml          # 群内词表（私有）
│   └── 群聊简介和概况.md   # 群背景说明（私有）
├── plans/                  # 历史设计规划文档
├── sandbox/                # 本地测试产物与调试截图
├── tools/
│   ├── tieba_login.py      # 贴吧登录态导出工具
│   └── log_server.py       # SSE 实时日志服务
└── docs/                   # 部署与开发参考文档（私有）
    ├── DEPLOY.md
    ├── LLM.md
    ├── MCP.md
    ├── REGEX_TUTORIAL.md
    ├── STRUCTURE.md
    └── ...
```

### `dev/.env` 与根 `.env` 的关系

- **根 `.env`**：本地 `python bot.py` 专用，HOST=127.0.0.1，含本机路径
- **`dev/.env`**：云端 Docker 专用，HOST=0.0.0.0，含 Docker 网络配置与镜像地址
- docker-compose 只读取 `dev/.env`，不再读取根 `.env`（二者互相独立）

### `llm_about` 部署路径

`llm_about/` 是 vocab.yaml 和 identities.yaml 的唯一生产部署路径。Docker 部署时应把仓库根目录的 `llm_about/` 挂载进容器：

- 宿主机 `llm_about/` → 容器内 `/app/llm_about/`

历史路径 `dev/llm_about/` 已弃用，不应再被 compose 挂载或由部署脚本读写。

---

## `.gitignore` 排除规则摘要

| 路径 | 原因 |
|---|---|
| `.env`, `.env.*` | 含真实密钥（`.env.example` 除外） |
| `config/llm.toml` | 含真实 provider 配置 |
| `config/llm.*.local.toml` | 同上 |
| `config/generation.toml` | 含真实多模态 provider 配置 |
| `config/chat_rules.toml` | 含私有群梗规则 |
| `config/personas/` | 含真实 persona 定义 |
| `data/` | 运行时数据 |
| `dev/` | 整个私有部署目录 |
