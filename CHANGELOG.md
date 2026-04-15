# Changelog

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 规范，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增

- 每日早中晚播报功能 `daily_briefing`：支持按群开启早报（08:00）、午报（12:00）、晚报（22:00），复用当前群绑定的 LLM provider/model/persona，结合消息数、活跃用户、热词和代表性消息样本生成短播报；消息量不足时自动退回模板播报；`/briefing on|off|status|now [morning|noon|evening]` 命令；`[daily_briefing]` 配置区块支持三段 cron、上下文规模、输出长度和模型级联
- Web 管理后台 `web_api.py` + `quickquip/app/web/`：基于 FastAPI 的独立管理 API 服务，提供消息统计、群级规则开关、每日总结/播报群组管理三个端点；前端为 Vue 3 SPA（`frontend/`），构建产物 serve 在 `/ops/` 路径；通过 `WEB_ADMIN_HOST`/`WEB_ADMIN_PORT` 环境变量控制监听地址（默认 `127.0.0.1:5104`）；新增 `GET /ops/api/groups/known` 返回已知群列表，`GET/PUT /ops/api/config/llm` 支持在线读写 `config/llm.toml`；前端新增配置编辑器标签页（原始文本编辑，保存前校验 TOML 语法），规则开关改为 pill toggle，操作反馈改为 toast，群组页支持从已知群下拉选择
- MCP docker transport 支持 `pull_policy` 配置项（`always`/`missing`/`never`，默认 `missing`），设为 `always` 可在每次重载时自动拉取最新镜像，解决镜像更新后工具列表不刷新的问题
- 新增 `/llm mcp reload` 命令（仅管理员）：强制 pull 所有 docker transport MCP 服务器的最新镜像并重连，完成后输出最新状态；非 docker transport 服务器仅重连不 pull
- 词云功能 `/wordcloud`（别名 `/词云`）：管理员可生成本群消息词频可视化图片，支持 `today`/`week`/`month`/`year` 四个时间窗口；独立消息收集层（`data/wordcloud_msgs/`），对所有群始终开启；图片以 base64 内联方式发送；依赖 jieba 分词 + wordcloud + Pillow，需在 `data/fonts/` 放置 NotoSansSC-Regular.ttf 字体文件
- 人格配置支持可选 `scope` 字段，`/llm personas` 会按群聊或私聊上下文只展示当前场景可用的人格
- `bot.py` 新增 loguru 文件日志输出，每日轮转写入 `data/logs/quickquip_YYYY-MM-DD.log`，保留 14 天；通过 nginx `/bot-logs/archive/` 路径（`auth_basic` 鉴权）可直接浏览下载
- 新增 `dev/tools/log_server.py`：SSE 实时日志服务，监听 `127.0.0.1:5103`，通过 nginx `/bot-logs` 路径（`auth_basic` 鉴权）在浏览器实时查看容器日志，支持关键词过滤和自动滚动
- `docker-compose.yml` 新增 `name: quickquip` 固定 compose project name，避免重复部署时因 project name 不一致导致 napcat 容器名冲突
- `LLM_TRACE_FLAG_FILE` 环境变量：指定一个 flag 文件路径，文件存在时 `provider.py` 以 INFO 级别输出完整的 LLM 请求/响应 JSON；配合 `log_server.py` 的 `/bot-logs/llm-trace` SSE 端点实现浏览器实时查看

### 修复

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

[Unreleased]: https://github.com/3aKHP/QuickQuip/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/3aKHP/QuickQuip/compare/bfdfcd0...v0.5.0
[0.2.0]: https://github.com/3aKHP/QuickQuip/compare/3dc2ab0...bfdfcd0
[0.1.0]: https://github.com/3aKHP/QuickQuip/commit/3dc2ab0
