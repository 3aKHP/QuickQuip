# Changelog

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 规范，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.8.1] - 2026-04-21

### 测试与 CI

- 测试套件整体重构：旧的 5 个顶层 `test_*.py`（共 2840 行断言式脚本，import 即执行、无 fixture、任一失败屏蔽后续）全部删除，改为 `tests/` 目录下的 pytest 套件（`unit/` + `integration/` + `fixtures/`），共计 193 个可独立运行的用例。新增 `requirements-dev.txt` 固定 `pytest` / `pytest-asyncio` / `pytest-cov` / `pytest-xdist` / `ruff` 版本；`pyproject.toml` 追加 `[tool.pytest.ini_options]`（markers: `playwright`/`slow`/`network`，默认跳过 playwright 与 network）与 `[tool.coverage.*]` 段
- 共享 fixtures 模块化：`tests/fixtures/` 下按职责拆分为 `onebot.py`（OneBot V11 dummy 消息族）、`provider_stubs.py`（4 个 LLM stub client，改为每实例独立状态）、`provider_fakes.py`（3 个 provider fake 子类保留真实序列化）、`mcp_io.py`（stdio 异步 I/O dummy）、`stream_chunks.py`（三家 provider SSE chunk 样本）、`configs.py`（`MIN_LLM_CONFIG_TOML` + `llm_service` pytest fixture）、`chain_game.py`（`make_chain_def` 工厂）
- CI 工作流替换为可复用模板：新 `.github/workflows/_tests.yml` 作为 `workflow_call` 模板，`ci.yml` 与 `release.yml` 双双改为瘦调用；新增 `concurrency` + `timeout-minutes` + `frontend` job（`npm ci && npm run build`）+ coverage.xml artifact 上传；原内嵌 TOML 校验 heredoc 和 CHANGELOG 提取脚本抽离到 `scripts/ci/validate_toml_examples.py` 与 `scripts/ci/extract_release_notes.py`，可本地复跑

### 修复

- `quickquip/chat/context_rules.py` 的 4 个 E402 lint 错误：`_extract_json` 函数定义将 `datetime` / `typing` / `quickquip.chat.config` / `quickquip.chat.text_rules` 的导入推后到了函数体之后，现将其归位到文件顶端

### 变更

- MCP 客户端重构：协议层与传输层解耦。新增 `Transport` 抽象基类 + `JsonRpcSession`（JSON-RPC id/pending-future/消息分发）+ 薄 `MCPClient`（initialize/tools 协议）三层；`StdioTransport` 合并原 stdio + docker 分支，`StreamableHttpTransport` 接管原 `HttpMCPClient`，新增 `SseTransport` 实现经典 MCP HTTP+SSE（GET 事件流 + `endpoint` 事件告知的 POST 地址）。`MCPClientManager` 对外 API 保持不变
- 彻底移除 DooD 支持：`MCPServerConfig.mount_docker_socket` 字段删除，不再自动挂载 `/var/run/docker.sock`；`dev/docker-compose.yml` 的 quickquip 服务同步摘掉 `/var/run/docker.sock:/var/run/docker.sock` 挂载；`transport = "docker"` 保留但只用于裸机环境执行 `docker run -i --rm ...`。容器化部署请改用 `http` 或 `sse` transport
- `config/llm.toml` / `config/llm.toml.example` 默认 MCP 清单清理：5 个只有 `docker` transport 的社区 server（github/tavily/arxiv/fetch/openweather）全部注释保留（裸机部署可手工启用），默认启用集只剩 `prts_wiki`（`transport = "http"`）
- `config/llm.toml.example` 更新 transport 文档段，列出 4 种传输方式；`README.md` 同步更新 MCP 配置说明

### 新增

- MCP 新增 `sse` transport（经典 MCP HTTP+SSE）：客户端 GET `url` 打开 SSE 长连接，服务端发送 `event: endpoint` 告知 POST 地址；后续请求 POST 到该地址，响应通过 SSE 流以 `event: message` 返回。支持 `headers` 字段传递鉴权头
- MCP sidecar POC：参考 `docker/mcp-example.Dockerfile.example` 用 `mcp-proxy` 包一层把 stdio-only 的上游社区镜像暴露为 SSE 服务，`dev/docker-compose.yml` 新增对应 sidecar service 跑在 compose 默认网络上，bot 通过 `transport = "sse"` 直连。此模式替代原先依赖 DooD 的 `transport = "docker"` 方案；新增 MCP 的模板化流程：写 Dockerfile、加 compose service、追加 `[[mcp.servers]]` 三步即可
- `docker/mcp-example.Dockerfile.example` ENTRYPOINT 模板要求追加 `--pass-environment` 标志。mcp-proxy 默认 `--no-pass-environment`，spawned 子进程拿不到容器 env，表现为 MCP server 侧报"<KEY> environment variable is required"，即便容器里已正确注入。模板注释补充了踩坑说明，下游复用时别漏
- `dev/deploy-v4.ps1` 部署时在远端对 `.env` / `dev/.env` 跑 `sed -i 's/\r$//'` 规范化行尾。Windows 编辑器常留下 CRLF，导致 Docker Compose 注入容器的 env 值尾部带 `\r`，表现为 API key 校验失败等奇怪错误（本次 POC 中 Tavily 首发报错即由此触发；后续清仓排进 ROADMAP）
- `MCPClientManager.sync()` 新增启动重试：每个 server 初始化失败时最多重试 3 次、间隔 2s。用于兜底 compose 冷启动时 sidecar 慢 1~3s 导致的"首次握手时 uvicorn 尚未 listening"竞态（典型现象：Python + uv venv 型 MCP 比 Alpine + Node 型慢几百 ms~几秒）

### 修复

- Web 管理后台贴吧标签页图片无法显示：`tiebapic.baidu.com` 对带 `Origin` 头的跨域请求返回 403，新增后端图片代理端点 `GET /ops/api/tieba/imgproxy?url=...`（仅允许 `*.baidu.com` 域名），前端封面图和详情图均改走代理

### 新增

- Web 管理后台贴吧标签页支持手动触发爬取：`GET /ops/api/tieba/sync?forum=...` 以 SSE 流式返回每条帖子的抓取进度；`crawler.collect_threads` 新增 `on_progress` 回调参数，`service.sync_now` 透传；前端页面头部新增"立即同步全部"按钮，每个贴吧条目右侧新增单吧同步按钮，同步过程实时展示日志面板，完成后自动刷新贴吧列表

- LLM 对话支持合并转发消息：用户在群聊/私聊中转发合并消息时，bot 自动通过 `get_forward_msg` API 拉取内容，将每条子消息格式化为编号列表（含发言者名/QQ 号）后注入 LLM 上下文；图片 URL 同步合并到多模态输入；`ExtractedLLMInput` 新增 `forward_text` / `forward_image_urls` 字段，`build_user_message_content` / `generate_reply` / `generate_private_reply` 全链路透传

## [0.8.0] - 2026-04-17

### 新增

- `rate_limit_rules` 支持 `scope = "group" | "global"` 字段：`scope="group"`（默认）按群独立分桶，群 A 的触发不消耗群 B 的预算；`scope="global"` 所有群 + 私聊合并到同一个桶，用于保护跨会话共享资源（LLM、搜索、爬虫）。built-in 规则中 `llm_chat`/`web_search`/`tieba_random_post`/`tavily_search` 标为 `global`，其余 6 条保持 `group`；`chat_rules.toml.example` 的 `[rate_limit_rules]` 文档段补充 `scope` 字段说明
- Web 管理后台新增"词云"标签页：后端 `GET /api/wordcloud/groups` 扫描 `data/wordcloud_msgs/` 列出有消息积累的群（显示天数和磁盘占用），`GET /api/wordcloud/render?group=...&window=today|week|month|year` 复用 `build_word_frequencies` + `render_wordcloud_bytes`，两个 CPU 密集步骤各自走 `asyncio.to_thread` 不阻塞事件循环，成功时返回 base64 PNG + Top50 词频 + 消息/词数统计；低于 50 词阈值返回 422，字体文件缺失返回 500 携带明确提示；前端提供群选择 + 时间窗 4 键切换 + "生成"按钮，左侧显示词云图（自带下载链接），右侧同步展示 Top 词频排行
- Web 管理后台新增"贴吧"标签页：只读视图 `tieba_service.store`，左侧列出所有已缓存贴吧与其同步状态（正常/同步中/错误/需登录），右侧分页展示帖子列表（标题 + 作者 + 封面 + 正文预览 + 图数 + 已发送过标记），支持按标题/正文/作者关键词过滤；点击任意帖子弹出 detail overlay 显示完整正文、所有配图、贴吧原链接；后端 `tieba.py` 路由对 `forum` 和 `tid` 做正则白名单校验（`[^\s/\\:]{1,32}` / `\d{1,20}`）防止路径穿越
- Web 管理后台新增"限流"标签页：`SlidingWindowRateLimiter` / `KeyedRateLimiter` 新增 `snapshot()` 方法在快照前就地 prune 掉过期时间戳并释放空 deque，`GET /api/rate-limit` 把每条限流规则的全局 used/limit、单用户 used/limit、窗口秒数、Top20 活跃用户按 user_id 一次返回；前端每条规则一张卡片，显示全局进度条 + 用户排行 mini bar，支持 5s 自动刷新（手动勾选），进程重启时所有窗口归零（符合内存实现的真实语义）
- Web 管理后台新增"群 LLM"标签页：按群覆盖 `llm.db` → `group_settings` 表中的 9 个字段（enabled / memory_enabled / provider_id / model / persona_id / trigger_prefix / allow_prefix / allow_at / history_limit）；三态语义支持"跟随默认/开/关"，每个文本/数值字段可点"跟随"按钮回落到 llm.toml 里的默认值；右侧表单仅在字段相对加载快照有变化时才 `PUT`（服务端使用 `model_dump(exclude_unset=True)` 仅落表被改的列），避免无谓 row 膨胀；后端路由 `group_settings.py` 额外暴露 `GET /api/group-settings/options`，把 `llm.toml` 里的 provider/persona 清单与当前 runtime/trigger 默认值一次返回给前端做下拉与 placeholder
- Web 管理后台新增"对话"标签页：浏览 `data/llm.db` 的 `conversation_messages` 表，左侧按 `group_id` 列出所有会话（群聊/私聊/归档自动分类），右侧以聊天流式展示消息（role 彩色标记、发送者名、时间、内容全文）；支持关键词过滤与游标翻页（`before_id`），可按单条删除用于回溯和脏数据清理；后端 `conversations.py` 用严格正则校验三种合法的 `group_id` 形态（`\d{5,12}` / `private:\d{5,15}` / `archive:\d{5,15}:\d{1,6}`）防止路径穿越
- "配置"标签页改造为多文件编辑器：新增 `chat_rules.toml` 的在线编辑入口，保留原 `llm.toml`；后端 `GET/PUT /api/config/llm` 泛化为 `GET/PUT /api/config/{key}`，新增 `GET /api/config` 列表端点；白名单机制防止路径穿越；页头补充"保存后需重启 bot 才会生效"提示；切换文件时若有未保存修改会弹确认
- Web 管理后台新增"人格"标签页：列出 `config/personas/*.toml`、读取/编辑单个 TOML、新建与删除；`_shared.toml` 标记为共享且不可删除；后端 `personas.py` 路由按照 `[A-Za-z0-9_][A-Za-z0-9_-]{0,63}` 强校验文件名防止路径穿越，写入前做 `tomllib.loads` 校验，并以 `filelock` 串行化并发写入
- Web 管理后台引入 `vue-router` 4（hash 模式）：`config/nav.js` 扩展 `path` 字段作为路由表唯一来源，`AppNav` 改用 `<router-link>`，支持 URL 深链接（`/ops/#/stats` 等）与浏览器前进后退；抽出 `composables/useAuth.js` 承载全局登录态、`composables/useAsyncData.js` 供后续新视图复用 loading/error/refresh 模板。hash 模式选择原因：nginx 端 `auth_basic` 外门和 FastAPI session cookie 内门的既有分层无需改动，任何深链刷新都只命中 `/ops/` 静态根，不需要额外的 SPA fallback 配置
- 语境感知回复子系统 `context_rules`：在普通 `[[rules]]` 与时区回复之间新增一层判定，`patterns` 首筛命中后再做上下文校验，只有语境合适时才触发；支持两种 `type`：`regex_context`（在最近 N 条消息中搜索 `context_conditions` 正则）和 `llm_context`（用超短 prompt 调用 LLM 返回 `{"trigger": true/false}` JSON）；LLM 判定带 `asyncio.wait_for` 超时（默认 2s）和按 `(rule_name, group_id, text)` 的 TTL 结果缓存（默认 60s，可通过 `llm_cache_ttl` 覆盖），降低常见触发词的调用成本
- `LLMService.quick_judge`：用于 `context_rules` 的极速判定入口，不走群配置 / 不注入记忆 / 不启用工具，单条 system+user prompt，`temperature=0.0`、`stream_enabled=False`
- 《新三国》梗默认入库（`chat_rules.toml.example`）：18 条直接 rules + 7 条 context_rules，共用 `new_three_kingdoms` 限流桶；`chat_rules.toml.example` 新增 `[[context_rules]]` 完整文档段与两条注释化示例

### 变更

- `KeyedRateLimiter` 内部存储从 `{rule_name: Limiter}` 升级为 `{(rule_name, bucket_key): Limiter}`，`allow()` 增加 `group_id` 关键字参数；`scope="group"` 的规则按群创建独立桶，`scope="global"` 的规则和无 `group_id` 的私聊调用都归到空桶；`snapshot()` 响应结构改为按规则列举多个桶，命中时为空的桶会在 snapshot 时 GC 掉；`/api/rate-limit` 响应与"限流"前端页随之更新，显示规则 scope 标签 + 每桶独立进度条
- `group_messages.py` 文本/语境规则的 `rate_limiter.allow()` 调用补传 `group_id=group_id`，其余 5 处调用（`llm_chat`/`web_search`/`tieba_random_post` 都是 global scope，或调用点无 group 上下文）保持原样
- `resolve_reply` / `build_reply` 改为 `async`，新增 `recent_context` 参数透传最近消息列表给 `context_rules`；调用方（NoneBot2 群消息适配层）同步更新

### 修复

- `chat_rules.toml.example` 中 `ntk_longerduo` 的 priority 从 83 抬到 95，避免 `扎聋我自己的耳朵` / `议论孔明先生` 被 `ntk_long` 单字正则（priority 92）提前截胡
- `rule_switch.SWITCHABLE_RULES` 改为在模块加载时动态并入 `TEXT_REPLY_RULES` / `CONTEXT_REPLY_RULES` / `CHAIN_GAME_CONFIGS` 里的规则名，修复 Web 管理后台规则开关页缺失 `kpl_*` 和新三国 `ntk_*` 系列规则开关的问题；系统/模块规则与历史规则名继续保留以兼容已有 `rule_switch.json`

## [0.7.0] - 2026-04-16

### 新增

- Web 管理前台设计升级：引入基于 CSS 变量的统一设计系统（`variables.css`/`transitions.css`），新增 `UiButton`、`UiCard`、`UiTag`、`UiPageHeader`、`UiIcon`、`UiLoading`、`UiEmpty`、`UiToggle` 等通用组件；导航改为配置驱动并预留学生成路由表的扩展接口；按业务域拆分 `api.js` 为模块化 API 层；统计页 Top 列表改为进度条可视化，登录页、规则页、记忆页等全部视图统一升级圆角卡片、阴影层次与响应式布局，并补齐移动端适配
- 每日早中晚播报功能 `daily_briefing`：支持按群开启早报（08:00）、午报（12:00）、晚报（22:00），复用当前群绑定的 LLM provider/model/persona，结合消息数、活跃用户、热词和代表性消息样本生成短播报；消息量不足时自动退回模板播报；`/briefing on|off|status|now [morning|noon|evening]` 命令；`[daily_briefing]` 配置区块支持三段 cron、上下文规模、输出长度和模型级联
- Web 管理后台 `web_api.py` + `quickquip/app/web/`：基于 FastAPI 的独立管理 API 服务，提供消息统计、群级规则开关、每日总结/播报群组管理三个端点；前端为 Vue 3 SPA（`frontend/`），构建产物 serve 在 `/ops/` 路径；通过 `WEB_ADMIN_HOST`/`WEB_ADMIN_PORT` 环境变量控制监听地址（默认 `127.0.0.1:5104`）；新增 `GET /ops/api/groups/known` 返回已知群列表，`GET/PUT /ops/api/config/llm` 支持在线读写 `config/llm.toml`；前端新增配置编辑器标签页（原始文本编辑，保存前校验 TOML 语法），规则开关改为 pill toggle，操作反馈改为 toast，群组页支持从已知群下拉选择
- Web 管理后台鉴权升级：FastAPI 层新增应用内 session 登录（`/ops/api/auth/login|me|logout`），所有管理接口统一要求 `HttpOnly` session cookie；`WEB_ADMIN_PASSWORD` / `WEB_ADMIN_SESSION_TTL_HOURS` / `WEB_ADMIN_COOKIE_SECURE` 等环境变量可直接纳入项目配置与部署流程
- MCP docker transport 支持 `pull_policy` 配置项（`always`/`missing`/`never`，默认 `missing`），设为 `always` 可在每次重载时自动拉取最新镜像，解决镜像更新后工具列表不刷新的问题
- 新增 `/llm mcp reload` 命令（仅管理员）：强制 pull 所有 docker transport MCP 服务器的最新镜像并重连，完成后输出最新状态；非 docker transport 服务器仅重连不 pull
- 词云功能 `/wordcloud`（别名 `/词云`）：管理员可生成本群消息词频可视化图片，支持 `today`/`week`/`month`/`year` 四个时间窗口；独立消息收集层（`data/wordcloud_msgs/`），对所有群始终开启；图片以 base64 内联方式发送；依赖 jieba 分词 + wordcloud + Pillow，需在 `data/fonts/` 放置 NotoSansSC-Regular.ttf 字体文件
- 人格配置支持可选 `scope` 字段，`/llm personas` 会按群聊或私聊上下文只展示当前场景可用的人格
- `bot.py` 新增 loguru 文件日志输出，每日轮转写入 `data/logs/quickquip_YYYY-MM-DD.log`，保留 14 天；通过 nginx `/bot-logs/archive/` 路径（`auth_basic` 鉴权）可直接浏览下载
- 新增 SSE 实时日志服务：监听 `127.0.0.1:5103`，通过 nginx `/bot-logs` 路径（`auth_basic` 鉴权）在浏览器实时查看容器日志，支持关键词过滤和自动滚动
- `docker-compose.yml` 新增 `name: quickquip` 固定 compose project name，避免重复部署时因 project name 不一致导致 napcat 容器名冲突
- `LLM_TRACE_FLAG_FILE` 环境变量：指定一个 flag 文件路径，文件存在时 `provider.py` 以 INFO 级别输出完整的 LLM 请求/响应 JSON；配合 `log_server.py` 的 `/bot-logs/llm-trace` SSE 端点实现浏览器实时查看

### 修复

- Web 管理后台安全加固（审计报告 H2-H6、M2-M4、M7-M10、L1-L2、L5、L9）：
  - 登录接口新增内存速率限制（每 IP 5 次失败/60s，超限封禁 300s）
  - `X-Forwarded-For` 仅在直连 IP 为 loopback/私有地址时才信任，防止 IP 伪造
  - CSRF 检查：Origin 和 Referer 均缺失时拒绝请求（返回 403），而非放行
  - `llm.toml` 写入改用 `filelock` 防止并发覆盖，并用 `try/finally` 确保临时文件不残留
  - `groups.py`、`rules.py` 统一 `group_id` 验证规则（5-12 位数字正则）
  - `memory.py`、`summaries.py` 数据库路径改为基于 `PROJECT_ROOT` 的绝对路径
  - Vite 开发代理路径从 `/api` 修正为 `/ops/api`，与生产环境一致
  - `api.js` 先处理 401 再解析 JSON，避免解析失败吞掉 HTTP 错误信息；401 触发后不再重复 toast
  - `MemoryView.vue`：confidence 空字符串传 `null` 而非 `""`，修复 422 校验错误；错误状态与"暂无条目"不再同时显示
  - `MemoryView.vue`、`SummaryView.vue`：群组列表加载失败时显示错误信息而非静默
  - `RulesView.vue`：checkbox 改用 `@click.prevent` 阻止浏览器默认切换，视觉状态完全由 Vue 控制
  - `App.vue`：`beforeUnmount` 时清理全局 `unauthorizedHandler`，避免 HMR 场景下旧闭包残留
  - 新增 `filelock>=3.12.0` 依赖
- LLM 引用消息认人：`build_user_message_content` 在有引用消息时，在 user message 里同时标注"当前提问者"和"引用发送者"，避免 LLM 跨 system/user 两层拼凑身份时张冠李戴
- LLM 上下文结构：`normalize_history` 统一历史消息格式，无 `user_id` 的旧消息不再裸露内容，改为标注"发言者：未知"；`build_messages` 将 recent_messages 块从序列头部移至紧贴当前提问之前，修正时间顺序（历史对话 → 触发前快照 → 当前提问）
- 每日总结发送：`_send_long_message` 始终通过 `send_group_forward_msg` 发合并转发卡片，不再对单段内容走 `send_group_msg` 直发（规避 NapCat ~667 汉字截断限制）
- 每日总结生成：模型级联现检查 `finish_reason`；Gemini 因 `SAFETY`/`RECITATION`/`MAX_TOKENS` 等非正常原因返回残缺内容时，自动降级至下一个模型，不再将截断文本写入数据库
- Tieba 爬虫 `load_thread_data`：改用 `page.request.get` 直接调 `pb/page_pc` API（共享浏览器上下文 cookie），不再依赖拦截页面 XHR，避免 Playwright 驱动加载时接口不触发的问题；细化登录态错误识别（`error_code` 2/4 或错误信息含"登录"）

## [0.6.0] - 2026-04-09

### 新增

- 每日群聊总结模块 `daily_summary`：凌晨 06:00 自动收集前一日聊天记录（06:00–06:00 窗口）并调用 LLM 生成约 2000 字小作文，中午 12:00 定时发布；以 persona 口吻撰写，注入群成员昵称对照表
- 模型级联策略：生成失败时自动降级到下一个 provider/model，顺序可在 `[daily_summary] model_cascade` 中配置，支持 `"@default"` 占位符指向当前群绑定的默认模型
- `/summary on|off|status|now` 命令：群管理员可开关本群每日总结；`now` 子命令立即生成前一天 06:00 至当前时刻的总结（每分钟限一次）
- `DailyMessageCollector`：逐行写入 `data/daily_msgs/{group_id}/{date}.jsonl`，生成后自动删除原始文件
- `DailySummaryStore`：独立 SQLite 文件 `data/daily_summaries.db` 持久化已生成的摘要
- `DailySummaryEnabledGroups`：群级功能开关（默认关闭，需主动开启），持久化至 `data/daily_summary_groups.json`
- `rule_switch` 新增 `"daily_summary"` 可切换规则，与 `/enable` / `/disable` 命令体系保持一致

## [0.5.0] - 2026-04-09

### 新增

- 通用接龙引擎 `ChainGameManager`，支持可配置步骤、`$N`/`$N[idx]` 捕获组占位符及 `|` OR 候选匹配；`GoodGirlChainManager` 委托其实现，保留全部公开 API
- `config/chat_rules.toml` 新增 `[[chain_games]]` 配置区块，支持自定义接龙游戏
- `/defectify`（别名 `/故障化`）命令，将文字/图片/引用消息转写为五字故障机器人风格别名，含笑点解析
- 私聊会话管理：`/start_session` 开启、`/end_session` 结束并自动存档（`--no-save` 跳过）、`/resume_session [N]` 恢复历史存档
- 私聊会话存档浏览 `/sessions`、删除 `/delete_session <N>` 及 `--preset "..."` 附加设定注入
- 撤回消息自动同步清除 LLM 对话历史；`/llm delete_msg` 支持手动删除超时无法撤回的消息
- 多来源贴吧池：`TIEBA_FORUM_KEYWORDS` 配置多来源；`/tieba source` 查看全部或指定来源状态
- 贴吧随机搬运：`/tieba`、`/tieba text`、`/tieba status`、`/tieba refresh`，基于 Playwright 合法登录态采集与缓存
- LLM 运行时基础设施：多 provider 支持（OpenAI / Claude / Gemini 三类协议）、人格注入、词表按需注入、时间元数据注入及图片识别
- LLM 工具调用链路与 MCP client；身份词表与群聊消息渲染
- 联网搜索后端：内置 SearXNG（含 Docker 容器编排配置）与 Tavily 兼容回退
- 消息统计 `/stats` / `/reset_stats`；群级规则开关 `/disable` / `/enable` / `/rules`
- 统计与规则开关跨重启持久化；APScheduler 定期自动保存
- provider `style_overrides` 字段，为特定模型追加 system prompt 修正段
- `/forget_all`（管理员），清空本群全部长期记忆
- `/llm context_limit <n>`（管理员），按群持久化设置对话上下文读取上限
- 结构化人格字段（`[identity]`/`[biography]`/`[cognition]`/`[instinct]`/`[voice]`/`[boundaries]`/`[world]`），自动编译为自然语言段落注入 system prompt
- `config/personas.example/` 示例目录，含结构化格式完整文档

### 变更

- 文字回复规则外部化到 `config/chat_rules.toml`（gitignored），`config.py` 仅保留基础参数
- 运行时重组为 `quickquip/` 主包，按 `adapters`/`app`/`llm`/`chat`/`tieba`/`search`/`common` 分层；`plugins/` 收窄为薄层 re-export 入口
- 人格配置从单文件 `config/personas.toml` 拆分为 `config/personas/` 目录，每个 `.toml` 对应一个人格；新增 `_shared.toml` 提取共享行为准则
- 私聊短期上下文读取/保留上限提升至 256 条
- 群聊 LLM 认人链路改进：短期历史持久化保存 QQ 号、显示名与标准身份，prompt 中注入参与者摘要
- SearXNG 默认引擎集调整，优先保留在中国大陆网络环境下易访问的搜索源

## [0.2.0] - 2026-03-16

### 新增

- `plugins/tz_utils.py`，承载时区计算与地点格式化纯函数

### 修复

- 修正 `tz_tracker.py` 文件命名拼写错误（原 `tz_tackcer.py`）
- 收窄 `like_reply` 触发范围；`i_do` 规则增加常见口语过滤
- 复读检测器与接龙管理器增加按群状态上限，防止长期运行内存增长

## [0.1.0] - 2026-03-16

### 新增

- 初始化项目骨架：NoneBot2 入口、插件目录与规则驱动回复逻辑
- 时区猜测、复读检测、好姐姐接龙、文字 meme 回复基础功能
- 说明文档、环境变量示例与基础测试脚本

[Unreleased]: https://github.com/3aKHP/QuickQuip/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/3aKHP/QuickQuip/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/3aKHP/QuickQuip/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/3aKHP/QuickQuip/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/3aKHP/QuickQuip/compare/bfdfcd0...v0.5.0
[0.2.0]: https://github.com/3aKHP/QuickQuip/compare/3dc2ab0...bfdfcd0
[0.1.0]: https://github.com/3aKHP/QuickQuip/commit/3dc2ab0
