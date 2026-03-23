# Changelog

本文件记录主仓库中已提交的可见变更。

## Unreleased

### feat: add fixed tieba random transport command

Git: `(Pending)`

- 新增固定贴吧随机搬运能力，支持 `/tieba`、`/tieba text`、`/tieba status`、`/tieba refresh` 指令
- 新增贴吧采集与缓存模块，使用 Playwright 合法登录态维护固定贴吧帖子池，并支持缓存避重与质量过滤
- 新增贴吧相关配置项、限流项、规则开关项与独立测试脚本
- 补充 README 中的贴吧功能说明、环境变量示例与测试说明

### feat: add llm tool calling and searxng search backend

Git: `f6cfb6c`

- 新增标准化工具调用链路，补齐工具消息结构、参数校验与 provider 协议映射
- 新增 MCP client 与工具桥接，支持按配置发现和执行外部工具
- 新增身份词表、消息渲染与短期消息检索能力，提升群聊上下文和称呼消歧质量
- 新增可切换联网搜索后端，支持项目内置 SearXNG 与 Tavily 兼容回退
- 新增 SearXNG 容器编排与配置文件，补充联网优先提示词、部署配置与测试覆盖

### feat: add llm, vision, and web search foundation

Git: `c128875`

- 新增 LLM 配置、运行时、持久化与 provider 适配层，支持 OpenAI、Claude、Gemini 三类协议
- 新增群级 LLM 控制命令、手动长期记忆命令与调试命令
- 新增人格注入、词表按需注入、时间元数据注入与严格受限的短期上下文
- 新增图片识别能力与 Tavily 联网搜索命令
- 新增 Docker / 远程部署收尾配置，支持挂载 `config/`、`data/` 与 `dev/llm_about/`
- 新增 LLM 与群内指令相关文档，并补充测试覆盖

### feat: persist stats and rule switch across restarts

Git: `e494665`

- 新增 `plugins/persistence.py`，提供 JSON 原子写入与安全读取
- `GroupStatsTracker` 与 `GroupRuleSwitch` 支持 `save()`/`load()` 序列化
- 启动时从 `data/` 目录加载已有数据，关闭时自动保存
- 每 5 分钟通过 APScheduler 定期自动保存
- `/disable`、`/enable`、`/reset_stats` 命令执行后立即持久化
- `.gitignore` 新增 `data/` 忽略规则

### feat: add random replies, scheduled messages, message stats, and group rule switch

Git: `678b5fe`

- 新增随机回复引擎：规则支持 `reply_templates` 加权随机列表（当前未配置，处于休眠状态）
- 新增定时消息模块 `plugins/scheduler.py`，基于 `nonebot-plugin-apscheduler`（当前未配置，处于休眠状态）
- 新增消息统计模块 `plugins/message_stats.py`，支持 `/stats` 查看群聊统计、`/reset_stats` 重置
- 新增群级规则开关 `plugins/rule_switch.py`，支持 `/disable`、`/enable`、`/rules` 命令（管理员权限）
- `plugins/tz_tracker.py` 集成统计与规则开关，`resolve_reply()` 支持按群跳过被禁用的规则
- `plugins/tz_config.py` 新增 `SCHEDULED_MESSAGES` 空配置
- `requirements.txt` 新增 `nonebot-plugin-apscheduler` 依赖
- 同步更新测试覆盖

## 2026-03-16

### fix: apply code review updates

Git: `bfdfcd0`

- 修正 `plugins/tz_tackcer.py` 文件命名并重命名为 `plugins/tz_tracker.py`
- 新增 `plugins/tz_utils.py`，承载时区计算与地点格式化相关纯函数
- 收窄 `like_reply` 触发范围，并为 `i_do` 增加常见口语过滤
- 为复读检测器与接龙管理器增加按群状态上限，控制长期运行时的内存增长
- 新增 `plugins/__init__.py`
- 同步更新测试、README、`.env.example` 与 `dev/` 忽略规则

### init: scaffold QuickQuip project

Git: `3dc2ab0`

- 初始化 QuickQuip 项目骨架
- 建立 NoneBot2 入口、插件目录与规则驱动回复逻辑
- 添加说明文档、环境示例与基础测试脚本

## 版本号对照表

| 版本 | Git |
|------|-----|
| 0.2.0 | `bfdfcd0` |
| 0.1.0 | `3dc2ab0` |
