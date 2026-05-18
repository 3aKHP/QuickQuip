# ROADMAP

本文件只记录 **当前主线** 与 **后续计划**。
已完成版本与历史变更请查看 [CHANGELOG.md](CHANGELOG.md)。

---

## 当前主线：v1.5.x LLM 流量合规层巩固

`v1.5.0` 引入了 LLM 流量敏感词过滤（输入 / 输出 / 历史 / 工具参数 / 工具结果五点接入），目标在于规避 provider 网关层审核累积风险和群聊违规内容外发风险。下一步重点是把这一层在生产环境锁稳，并补齐尚未覆盖的角落。

### 本轮关注点

1. **生产环境观测期**：跟踪 `quickquip.common.sensitive_filter` 日志，评估词表覆盖度与误伤率，按命中频率反推词表调整方向。
2. **思考块（reasoning_content）扫描**：OpenAI 兼容协议的 `reasoning_content` 是纯文本，可以接入 scrub；Claude 的 signed thinking 块带签名，scrub 后签名失效，需评估是否整块丢弃或仅在写入历史时清理。
3. **每日总结 / 播报 / 词云链路加固**：这些路径目前未接入过滤器，但同样会把群聊原文送给 LLM。需评估是否在消息收集阶段统一过一遍。
4. **Provider 适配评估**：MiMo `mimo-v2.5-pro` / `mimo-v2-pro` 已标记为 `non_vision_models`；后续若新增国产 provider，需统一通过 `non_vision_models` 与 `style_overrides` 接入，避免临时打补丁。

### 退出条件

1. 生产观测期至少一个完整月度周期，无 provider 网关层 400 累积。
2. thinking 块扫描在所有启用 thinking 的 provider 上验证通过。
3. 关键合规事件能从日志反推到具体类别和命中位置（不需要原文）。

---

## 下一阶段候选

### 本地 TTS 服务接入

远程 TTS 已通过 `config/generation.toml` 的 `[audio]` provider 实现。本条目的目标是补充本地 HTTP TTS provider 作为 fallback 或独立模型来源，首期只覆盖轻量、短文本、固定音色场景。

### `config/llm.toml` 热重载增强

`/llm reload` 目前可重读配置并重建部分运行时对象，但 provider 客户端和若干状态仍以保守策略处理。后续若要做更彻底的热切换，需要先设计 in-flight 请求、MCP reconnect 与状态收束的顺序。

### Provider 健康检查自动故障转移

`quickquip/llm/health.py` 已具备单次检查、探活和敏感词过滤器可观测性。下一步可评估：

1. 定时健康检查（cron 化）
2. provider 健康排序
3. 自动降级或故障转移（基于网关错误类型分类，含 `Content Exists Risk` 这类合规事件）

### 测试覆盖继续补强

在当前 pytest / CI 体系基础上，继续补：

1. provider 真实 payload 回归库
2. 前端组件测试
3. 并发安全测试
4. 模板渲染负例测试
5. 性能基准测试

---

## 长期 / 待评估方向

### LLM 主动发言

冷场检测：群内超过 N 小时无消息且处于活跃时段时，bot 主动发一条话题引子（从词云高频词、每日总结或名言录取材）。

### 群周报 / 月报

在每日总结基础上扩展更长周期的聚合内容，例如热词趋势、活跃榜/新人榜、本群大事记。

### 平台适配扩展

`adapters/nonebot/` 已将协议层与业务层隔离。若未来确有需求，可评估接入 Telegram 或 Discord 等适配器。

### 头像梗图生成

结合 QQ 头像生成群内梗图（如摸头、拍打等），风格上契合项目气质，但模板维护成本较高，暂列远期。

---

## 明确不做的事

- 把全天候群消息无差别塞进长期记忆
- 跨群共享人格状态
- 把 `群聊简介和概况.md` 全文直接注入模型
- 各平台链接解析
- 在 OneBot V11 下追求伪流式输出
