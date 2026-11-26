<!-- Generated from docs/dev/architecture.md; do not edit -->

# QuickQuip 项目架构与结构

本文面向开发者和部署维护者，说明仓库目录、代码分层、依赖方向，以及公开分发内容和私有部署资产的存储位置。

开发文档的公共／私有边界与职责索引见 [`README.md`](README.md)；源码结构规则见 [`style.md`](style.md)。

项目概念见[术语表](../glossary.md)，重要技术选择的背景和取舍见[架构决策索引](adr/README.md)。其中，[领域分层与装配](adr/0006-layered-architecture-composition.md)、[统一聊天归档](adr/0007-unified-chat-archive.md)和[事务部署](adr/0011-transactional-deployment-recovery.md)记录本页核心结构的依据。

---

## 核心概念：分发层与自用层

| 层 | 含义 | 存储位置 |
|---|---|---|
| **分发层** | 可公开分发的通用代码、公开文档与示例模板 | 追踪到 Git（公共仓库可见） |
| **自用层** | 私有部署配置、群聊运行数据、认证密钥与本地工作材料 | `.gitignore` 排除（不进入版本控制） |

凡是含有真实密钥、个人信息、群内私有内容的文件，均属自用层，必须由 `.gitignore` 排除。

---

## 两种部署模式

| 模式 | 入口 | 环境变量来源 |
|---|---|---|
| 本地直接运行 | `pip install -e .` 后 `python bot.py` | 根目录 `.env` |
| 容器化部署 | `prod/` 私有部署编排 | 根目录 `.env` |

---

## 三层架构

QuickQuip 代码组织为三层结构：

1. **业务逻辑层** — `src/quickquip/` 下的 `chat`、`common`、`configuration`、`config_sync`、`config_workspace`、`environment`、`llm`、`games`、`sts`、`tieba`、`search` 和 `generation`，独立于聊天框架运行
2. **框架适配层** — `src/quickquip/adapters/nonebot/`（所有 NoneBot2 matcher、command、生命周期钩子与出站守卫注册在此）
3. **插件发现薄层** — `src/plugins/`（仅通过 re-export 暴露插件对象，供 NoneBot2 加载）

消息流顺序：

```text
NoneBot2 event → tz_tracker_plugin matcher
               → self_message_events (message_sent, priority 1, block=True)：群自消息归档，私聊自消息终止
               → group_messages.register_message_matcher (priority 60, block=False)
               → llm_service.generate_reply() [if LLM triggered]
                  or resolve_reply() [rule-based fallback]
```

规则回复链路：

1. `repeat_detector` — 复读／刷屏检测（最高优先级）
2. `good_girl_chain` / `custom_chain_games` — 接龙状态机（60s 超时）
3. `game_registry.process()` — 会话型游戏分发
4. `text_reply_rules` — 正则彩蛋匹配（优先级 + 加权随机）
5. `context_rules` — 语境感知规则（`regex_context` / `llm_context` 判定）
6. `build_timezone_reply()` — 时区猜测
7. STS `card_le` — “xxx了”公式，位于规则链末尾。`resolve_reply()` 中的 `match_card_le` 分支先执行“X了”正则快筛、规则开关、限频预检和概率掷骰，通过后再发起 LLM 判定

规则回复经过群级 `rule_switch.is_enabled()` 检查，管理员可切换的规则由 `SWITCHABLE_RULES` 登记；内置游戏的操作与停用范围见[游戏管理](../admin/game-config.md#配置范围)。单条消息在整条回复链路中最多执行一次触发概率掷骰：已在匹配器内部完成掷骰的分支（`text_reply_rules`、`context_rules` 以及快筛通过后的 `card_le`）会在候选结果中写入 `PROBABILITY_CHECKED` 标记，使 `resolve_reply()` 出口跳过二次掷骰；复读、接龙、游戏和时区猜测则统一在 `resolve_reply()` 出口按对应限流桶键掷骰；显式 LLM、群聊被动唤醒和无聊唤醒在各自发送路径独立掷骰，私聊按用户隔离状态。未配置概率的规则默认放行回复。

消息实际外发前，由 `rate_limit.allow()` 检查限流、`stats_tracker` 记录消息统计与规则触发次数；普通文本与超长消息转长图（`long_messages.py`，含日报、周期报告与人物志在合并转发不可用时的单张长图自动降级）均经过 `sensitive_filter` 扫描，最终由适配层的全局 OneBot 出站守卫（`outbound_guard.py`）在协议 API 调用出口统一拦截违规内容。

### 依赖方向与组合根

依赖方向为：`plugins → adapters/nonebot → app 与业务域`，以及 `app → 业务域 → common`。实际消息入口可以同时使用 `app` 暴露的已装配能力与框架无关业务函数，但框架无关业务域不得反向导入 `app`、NoneBot 或 Web 展示层。

- `app/message_pipeline.py` 是应用组合根：创建共享依赖、绑定生命周期并暴露经装配的能力；领域策略、协议解析和持久化规则由各自领域拥有。
- `adapters/nonebot/` 将 OneBot 事件、命令和调度适配为领域调用，不在适配层实现可脱离 NoneBot 的业务算法。
- `app/web/` 是 Web Admin 的 FastAPI 装配和路由层。路由通过公开应用能力读取或触发运行时操作，不能复制 LLM、聊天、游戏或持久化领域规则。
- `llm/provider/` 只处理规范化请求／响应和渠道协议。MCP、工具执行、群策略、存储、Trace 展示和应用生命周期分别由拥有它们的模块负责。

跨层共享时传递窄能力或领域接口，不以整个应用对象或内部单例作为通用依赖。完整的重构判断标准见 [`style.md`](style.md)。

---

## 根目录

```text
QuickQuip/
├── bot.py                  # NoneBot2 启动入口
├── web_api.py              # Web 管理后台入口（独立进程，监听 5104）
├── webview_launcher.py     # Windows 桌面壳启动器
├── start.bat               # Windows 一键启动脚本
├── Dockerfile              # 本地构建镜像
├── pyproject.toml          # 项目元数据与依赖声明
├── requirements.txt        # pip 安装用依赖列表
├── requirements-dev.txt    # 开发期依赖（lint / 测试）
├── .env.example            # 部署环境变量模板
├── .env                    # 部署真实涉密环境变量（gitignore）
├── src/                    # Python 源码（src layout）
│   ├── quickquip/          # 业务逻辑包
│   └── plugins/            # NoneBot2 插件入口薄层
├── tests/                  # pytest 测试套件与发行物验收套件
├── scripts/                # 按部署、巡检、维护、检查、CI 与钩子分类的工具程序
├── frontend/               # Web 管理后台前端（Vue 3 SPA）
│   ├── src/                # 源码
│   └── dist/               # 构建产物（gitignore）
├── docker-compose.example.yml  # Docker Compose 编排示例（含内置 SearXNG 与 env-agent）
├── docker/
│   ├── Dockerfile.prod     # 生产镜像构建
│   └── searxng/
│       └── settings.yml    # SearXNG 配置
├── config/                 # 配置文件目录（见下文专节）
├── llm_about/              # vocab / identities 唯一生产部署路径（见下文专节）
├── docs/                   # 公开文档（按 user / admin / dev 读者角色组织）
├── skills.example/         # 预置官方 Skill 模板（复制到 skills/ 启用）
├── prod.example/           # 生产运维目录模板（追踪）
├── prod/                   # 真实生产运维目录（gitignore，由 prod.example/ 复制）
├── CHANGELOG.md            # 变更记录
├── ROADMAP.md              # 演进方向
├── CONTRIBUTING.md         # 贡献指南
├── SECURITY.md             # 安全政策与漏洞上报
├── CODE_OF_CONDUCT.md      # 行为准则
├── CLAUDE.md               # AI 协作入口文档
├── LICENSE                 # 许可证
└── README.md               # 项目入口与快速开始
```

---

## `src/quickquip/` — 业务逻辑包

项目采用 src layout，源码位于 `src/` 下，业务包通过 `quickquip.*` 导入。

```text
src/quickquip/
├── chat/                    # 框架无关的聊天业务（时区猜测、复读、彩蛋规则、接龙、统计、规则开关、语境规则、聊天归档与只读历史查询、群语录、离线留言、每日总结/播报与周期报告编排、唤醒、词云、节日检测）
├── common/                  # 通用基础组件（限流、持久化、消息去重、最近消息缓冲、敏感词过滤器、共享成员身份与结构化记录正文）
├── configuration/           # 受管配置归属、逻辑快照、字段合并、原格式文本保留、进程监管与持久写入
├── config_sync/             # qqsync 单向配置同步、远端安装、SSH/Compose 协调与部署恢复事务
├── config_workspace/        # qqconf 本地可编辑工作副本编码、布局、候选生成与崩溃恢复
├── environment/             # env-agent 只写根环境变量存储、静态消费目录投影与私有套接字通信
├── games/                   # 游戏模块（registry、scores、economy、config、各游戏实现）
├── llm/                     # LLM 运行时（四协议 provider、客户端指纹、会话与纪元窗口、Persona v3 编译、工具调用与发现、群历史/语录/记忆工具、Skill、MCP 客户端、健康检查、用量计费、quick_judge、single_shot；服务门面拆至 service_parts/）
├── generation/              # 多模态输入/产出（图片/TTS/音乐渠道调用、ASR 语音转写、受限子进程 SILK/AMR 原始语音转码、本地 resvg 子进程沙箱 SVG 渲染）
├── tieba/                   # 贴吧爬虫与帖子池
├── search/                  # 项目内 SearXNG 搜索客户端，以及 Responses web.run 独立搜索命令 Schema 与结果解析
├── sts/                     # 杀戮尖塔公式化回复（lexicon、formulas/card_le、formulas/defectify）
├── adapters/
│   └── nonebot/             # NoneBot2 适配层（生命周期、群/私聊入口、语音提取、长文本转长图、全局 OneBot 出站守卫、命令与定时任务；命令按域拆至 command_parts/）
└── app/                     # 应用级组合根（单例初始化、状态加载、游戏注册与优雅关闭）
    └── web/                 # Web 管理后台 FastAPI 应用、Session 鉴权与路由
        └── routes/          # API 路由（统计、规则、群组、群组设置、记忆、总结、周期报告、对话、会话纪元、人格、资料、LLM 配置、思考档位、LLM 运行时、LLM 用量、配置、环境变量、Skill、日志、限流、贴吧、词云、诊断、敏感词状态、MCP 面板、调度器监控、定时消息、审计、金币经济、牛牛大作战、唤醒、语录）
```

**规则**：业务逻辑只进 `src/quickquip/`（包路径 `quickquip.*`），不进 `src/plugins/`。NoneBot2 相关 import 只在 `adapters/nonebot/` 里出现。

分层依赖方向、文件长度预警线、抽取触发条件、反模式与重构节奏等硬原则见 [`style.md`](style.md)。

---

## `src/plugins/` — NoneBot2 插件入口层

源码位于 `src/plugins/`。每个文件都是薄层 re-export，把 `quickquip.*` 里的对象暴露给 NoneBot2 插件发现机制，不含任何业务逻辑。

`bot.py` 通过 `nonebot.load_plugins(*plugins.__path__)` 加载已安装的 `plugins` 包路径。

---

## `frontend/` — Web 管理后台前端

Web Admin 前端是独立的 pnpm 工程（`quickquip-admin-v2`），技术栈为 Vue 3.5 + TypeScript strict + Vite 8 + vue-router 4（hash 模式，base `/ops/`）。关键约定：

- 路由页面在 `src/config/nav.ts` 登记，路由由其派生；除首页静态引入外，页面组件一律路由级动态 import。
- 后端接口封装按领域收在 `src/api/`，可复用状态与请求编排收在 `src/composables/`，`src/components/ui/` 是设计系统组件。
- 构建产物 `frontend/dist/`（gitignore）由 `app/web/` 以 StaticFiles 挂载到 `/ops/`；前端不设路由守卫，鉴权由后端强制。

开发命令、测试双栈与部署形态见 [`../../frontend/README.md`](../../frontend/README.md)。

---

## `config/` — 配置文件目录

| 文件 | 层 | 说明 |
|---|---|---|
| `llm.json.example` | 分发层（追踪） | LLM 配置数据库的 JSON 交换示例 |
| `llm.toml.example` | 分发层（追踪） | 旧版 TOML 格式参考与迁移输入示例 |
| `llm.toml` | 迁移资产（gitignore） | 首次迁移输入与迁移前版本回退配置 |
| `generation.toml.example` | 分发层（追踪） | 多模态输入／产出配置模板 |
| `generation.toml` | 自用层（gitignore） | 真实图片／TTS／ASR／音乐／SVG 配置 |
| `awakening.toml.example` | 分发层（追踪） | 群聊唤醒模块配置模板 |
| `awakening.toml` | 自用层（gitignore） | 真实唤醒阈值、兴趣话题和按群覆盖 |
| `sensitive_words.toml.example` | 分发层（追踪） | 敏感词过滤器配置模板 |
| `sensitive_words.toml` | 自用层（gitignore） | 部署者填充的敏感词词表 |
| `chat_rules.toml.example` | 分发层（追踪） | 文字回复规则格式示例 |
| `chat_rules.toml` | 自用层（gitignore） | 部署专用的彩蛋规则（群内私有梗） |
| `games.toml.example` | 分发层（追踪） | 游戏参数配置模板 |
| `games.toml` | 自用层（gitignore） | 游戏参数（金币倍率、CD、赌注上限等） |
| `niuniu_text.toml.example` | 分发层（追踪） | 牛牛自定义文案模板 |
| `niuniu_text.toml` | 分发层（追踪） | 默认自定义牛牛文案（勿写入私有内容） |
| `niuniu_text_safe.toml.example` | 分发层（追踪） | 牛牛和谐版文案模板 |
| `niuniu_text_safe.toml` | 分发层（gitignore 除外，追踪） | 默认和谐版牛牛文案（勿写入私有内容） |
| `personas.example/` | 分发层（追踪） | Persona 配置格式示例（含 v3 三段式与共享准则） |
| `personas/` | 自用层（gitignore） | 真实 Persona 定义（含角色设定、声腔、百科等） |

部署者从 `.example` 复制私有配置，再编辑自己的配置文件与 `personas/`；LLM 配置通过数据库草稿管理。贡献者在格式或示例行为变化时同步更新公开模板。

`niuniu_text.toml` 和 `niuniu_text_safe.toml` 是受追踪的分发文件，内容须适合公开。私有文案放在未被追踪的独立文件中，通过 `games.toml` 的 `niuniu_text_path` 或 `niuniu_safe_text_path` 指向，字段说明见[配置参考](../admin/configuration.md)。

---

## 受管配置存储

`config/managed/config.db` 集中保存 SQLite 配置及本机配置历史，`config/managed/scheduled_messages.json` 保存循环任务。生产部署共享挂载该目录，Bot 与 Web 通过领域仓储写入。发布执行状态、私聊活跃状态和业务记录保存在运行存储，具体归属与事务见[配置与运行存储](configuration-storage.md)。

## `data/` — 运行时持久化数据（自用层，gitignore）

```text
data/
├── stats.json                      # 群消息统计与观察到的成员名片
├── rule_switch.json                # 群规则开关状态
├── pending_scheduled_messages.json # 一次性定时消息待办队列
├── client_identity.json            # 部署级随机客户端安装身份
├── llm.db                          # LLM 对话历史、会话身份、长期记忆、执行记录与群历史查询开关（SQLite）
├── daily_summaries.db              # 每日群聊总结存档（SQLite）
├── period_reports.db               # 周期报告（周报/月报）存档（SQLite）
├── weekly_report_groups.json       # 已启用周报的群列表
├── monthly_report_groups.json      # 已启用月报的群列表
├── web_admin_sessions.db           # Web Admin 会话记录（SQLite）
├── web_admin_actions.db            # Web Admin 到 Bot 进程的通用动作队列（SQLite）
├── audit.db                        # Web Admin 操作审计日志（SQLite）
├── llm_trace.db                    # LLM HTTP 调用索引与请求/响应报文（SQLite，保留 14 天）
├── trace_blobs/                    # LLM Trace 剥离的内联 base64 媒体内容寻址存储
├── config_runtime.db               # 发布指针、控制任务固定输入、执行状态与 Bot 心跳（SQLite）
├── environment/                    # env-agent 只写环境变量版本、待删除标记与进程快照
├── llm_usage.db                    # LLM Token 用量与成本统计（SQLite）
├── mcp_status.json                 # MCP 服务装载状态快照
├── cron_jobs.json                  # Cron 定时任务调度状态快照（Bot 写，Web Admin 读）
├── awakening_boredom_groups.json   # 已启用无聊唤醒的群列表
├── game_economy.db                 # 游戏金币 / 签到 / 好感度（SQLite）
├── game_scores.json                # 游戏战绩计分
├── niuniu.db                       # 牛牛大作战状态与操作流水（SQLite）
├── offline_messages.db             # 离线留言（SQLite）
├── quotes.db                       # 群语录（SQLite）
├── chat_archive.db                 # 统一聊天记录归档（SQLite，日报/词云/播报/周月报/群历史查询共用，永不自动删除）
├── daily_msgs/                     # 旧每日消息 JSONL（已退役，仅回灌脚本读取后可清理）
├── wordcloud_msgs/                 # 旧词云消息 JSONL（已退役，仅回灌脚本读取后可清理）
├── logs/                           # loguru 文件日志（保留 14 天）
├── fonts/                          # 中文字体文件（手动放置，词云 / SVG 渲染 / 长消息转长图共用）
├── tieba/
│   ├── pool.json                   # 贴吧帖子池
│   └── storage_state.json          # 贴吧登录态（Playwright 导出）
└── searxng/                        # SearXNG 运行缓存
```

---

## `docs/` — 面向读者的公开文档（分发层）

```text
docs/
├── index.md                        # 文档总导航
├── glossary.md                     # 跨文档统一术语表与契约入口
├── user/                           # 面向群友
│   ├── group-commands.md
│   ├── group-games.md
│   ├── llm-skills.md
│   ├── llm-tool-discovery.md
│   ├── private-commands.md
│   └── three-kingdoms-memes.md
├── admin/                          # 面向部署者/管理员
│   ├── installation.md
│   ├── deployment.md
│   ├── storage-migration.md
│   ├── onebot-adapters.md
│   ├── configuration.md
│   ├── llm-configuration.md
│   ├── config-workspace.md
│   ├── config-sync.md
│   ├── environment.md
│   ├── client-fingerprints.md
│   ├── memory.md
│   ├── record-identities.md
│   ├── sensitive-filter.md
│   ├── skills.md
│   ├── mcp-servers.md
│   ├── tool-discovery.md
│   ├── game-config.md
│   ├── global-admins.md
│   ├── migration-napcat-to-llbot.md
│   └── web-admin.md
└── dev/                            # 面向开发者（规范、架构、模块契约、教程与 adr/ 决策记录）
```

---

## 私有部署材料

真实部署脚本配置、运维通知密钥、Compose 私有覆盖和临时分析材料均属自用层。公开文档记录可公开分发的配置格式、模板和运行方式。

### `prod.example/` 与 `prod/`

- `prod.example/`：生产 Compose 和运维通知配置模板。
- `prod/`：Git 忽略的实际 Compose 和运维配置。OneBot 协议端由部署者独立部署维护，边界见 [ADR-0032](adr/0032-swappable-onebot-backend.md)。
- `scripts/deploy/`、`scripts/ops/`：由 Git 维护的部署和巡检程序；[脚本导航](../../scripts/README.md)说明各子目录职责。
- `docker/Dockerfile.prod`：生产镜像构建文件，构建参数通过 Compose 和根目录 `.env` 配置。
- 本地私有工作区保存草稿、测试沙箱、探针脚本和内部工作文档。

### 私有环境变量与根 `.env` 的关系

- **根 `.env`**：QuickQuip 应用唯一的涉密环境变量来源，供本地运行与 `prod/` 容器部署共同读取，必须保持 `.gitignore` 排除。
- **`prod/sendkey.env`**：可选运维通知密钥，仅由巡检脚本读取，不被 QuickQuip 应用加载。

### `llm_about` 部署路径

`llm_about/` 是 `vocab.yaml` 和 `identities.yaml` 的唯一生产部署路径。Docker 部署时应把仓库根目录的 `llm_about/` 挂载进容器：

- 宿主机 `llm_about/` → 容器内 `/app/llm_about/`

Compose 挂载与部署脚本共用上述统一路径。

---

## `.gitignore` 排除规则摘要

| 路径 | 原因 |
|---|---|
| `.env`, `.env.*` | 含真实密钥（`.env.example` 除外） |
| `config/managed/` | SQLite 配置与循环任务，包含私有配置 |
| `config/llm.toml` | 首次迁移输入与迁移前版本回退资产 |
| `config/llm.*.local.toml` | 旧部署的本地覆盖资产 |
| `config/generation.toml` | 含真实多模态 provider 配置 |
| `config/awakening.toml` | 含真实唤醒阈值、兴趣话题和群覆盖 |
| `config/sensitive_words.toml` | 含部署者填充的敏感词词表 |
| `config/chat_rules.toml` | 含私有群梗规则 |
| `config/games.toml` | 含游戏参数配置 |
| `config/personas/` | 含真实 Persona 定义 |
| `skills/` | 部署者安装的运行期 Skill 包（`skills.example/` 除外） |
| `data/` | 运行时持久化数据 |
| `prod/` | 真实生产运维目录与运维通知密钥 |
| 本地私有工作区 | 本地开发草稿、沙箱、探针脚本和内部工作文档 |
