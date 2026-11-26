<!-- Generated from ROADMAP.md; do not edit -->

# ROADMAP

本文件说明 QuickQuip 的规划原则、长期演进主线与明确排除的方向。具体的候选提案、调研备忘与进度统一在 GitHub Issues 的 [`roadmap`](https://github.com/3aKHP/QuickQuip/issues?q=is%3Aopen+label%3Aroadmap) 与 [`memo`](https://github.com/3aKHP/QuickQuip/issues?q=is%3Aopen+label%3Amemo) 标签下跟踪；已发布版本的变更记录见 [`CHANGELOG.md`](CHANGELOG.md)。

一个方向进入具体版本计划前，需先在对应 Issue 中明确目标、验收标准、风险边界与验证方式。

---

## 规划原则

1. **小规模部署优先**：优先服务个人与熟人小群场景，保持配置清晰、运维成本可控。
2. **稳定性先行**：涉及 LLM、定时任务、Web Admin、部署脚本和数据持久化的改动，优先补齐可观测性与回滚路径。
3. **功能分层落地**：新能力先以可控试点验证，稳定后再扩展配置入口、文档与管理后台。
4. **公共文档同步**：面向用户、管理员和开发者的行为变化，在同一变更中同步 `README.md`、`docs/`、配置模板与变更草稿。
5. **保守处理高风险输入**：涉及敏感词过滤、工具调用、外部搜索、群聊历史与长期记忆的方向，先冻结安全边界。

---

## 当前演进主线

以下为目前正在公开跟踪的主要方向，详细讨论与待决问题见对应 Issue：

- **LLM 上下文、记忆与成本优化**
  - 在群历史查询落地的基础上，评估后台补记与定期记忆整理（[#329](https://github.com/3aKHP/QuickQuip/issues/329)）。
  - 持续分析并优化请求前缀缓存命中率与跨轮请求体结构一致性（[#353](https://github.com/3aKHP/QuickQuip/issues/353)、[#289](https://github.com/3aKHP/QuickQuip/issues/289)）。
  - 优化 STS“xxx了”被动匹配的模型调用成本与时延（[#189](https://github.com/3aKHP/QuickQuip/issues/189)）。
- **内容安全、鉴权与配置演进**
  - 评估内容安全过滤在模型推理过程（reasoning）以及独立报告输入／存档正文阶段的剩余策略（[#360](https://github.com/3aKHP/QuickQuip/issues/360)）。
  - 评估为 Web Admin 增加 TOTP 登录与敏感操作二次验证（[#346](https://github.com/3aKHP/QuickQuip/issues/346)）。
  - 结合 `qqconf` 工作副本的实际使用反馈，评估其余独立配置文件是否进一步迁入 SQLite（[#316](https://github.com/3aKHP/QuickQuip/issues/316)）。
- **互动体验与运行效率**
  - 重做 `/tts` 语音合成交互，提供更简短的命令形态与音色库浏览（[#261](https://github.com/3aKHP/QuickQuip/issues/261)）。
  - 为临时 I/O、内存与 LLM Trace 建立容量可观测性与预算约束（[#80](https://github.com/3aKHP/QuickQuip/issues/80)）。
  - 视实际需求评估更轻量的镜像分发形态、原生音视频多模态输入以及更丰富的周期报告生成体验。
- **远期架构（潜在 2.0 门槛）**
  - 建立版本化的标准化扩展插件接口（[#73](https://github.com/3aKHP/QuickQuip/issues/73)），使受信任扩展可通过统一上下文注册命令、消息处理、LLM 工具、定时任务、配置与独立存储，并由插件管理器追踪资源归属与生命周期。

---

## 长期观察

以下方向在方向上契合项目，但暂不安排具体里程碑：

- **更主动的群聊参与**：在现有低频唤醒基础上，结合冷场话题、词云热词与群内语录探索频率可控的主动互动。
- **跨平台协议适配**：`src/quickquip/adapters/nonebot/` 已将协议层与业务层隔离，有明确场景时再评估接入 Telegram、Discord 等其他适配器。
- **头像梗图生成**：结合成员头像生成群内梗图，但模板维护、缓存与滥用控制成本较高，暂不优先投入。

---

## 明确排除的方向

- 全天候群消息无差别写入长期记忆
- 跨群共享人格状态
- 将群聊简介全文直接注入模型
- 各平台链接解析大全
- OneBot V11 下的伪流式输出
