# 敏感词过滤器（sensitive_filter）

QuickQuip 在 LLM 流量入口和出口处都接了一层敏感词过滤，目的是：

1. **防止账号被封**：触发 LLM 提供商网关层审核（如 DeepSeek 的 `Content Exists Risk`、阿里云的 `Content security warning`）多次后，API Key 可能被封禁
2. **防止群被炸**：模型生成的违规内容如果被 bot 发到群里，群本身和发言群员（即使是 bot）都可能被处罚
3. **减少历史污染**：旧消息中的敏感内容如果继续作为 context 注入下次请求，会持续触发问题

过滤器位于 `quickquip/common/sensitive_filter.py`，由词表配置文件 `config/sensitive_words.toml` 驱动。**该词表文件被 gitignored，必须由部署者自行填充。**

## 工作原理

### 两级匹配

- **block 级**：命中即中断
  - 输入侧命中：直接返回固定回复，**不调用 LLM**（既防止账号被审核标记，也节省 token）
  - 输出侧命中：替换为兜底回复，**不写入历史**（防止污染下一轮 context）
  - 历史侧命中：用 `[内容已屏蔽]` 替换，仅影响当次注入到 LLM 的 messages，**不修改数据库存储的原文**

- **soft 级**：仅记录日志，不阻断
  - 用于监控边缘词、推广话术等。日志累积一段时间后可以人工评估是否提升为 block

### 算法

纯 Python 实现的 **Aho-Corasick 自动机**，对几千词级别的词表，单次扫描 < 1ms，无需引入 C 扩展依赖。

匹配前会做轻量归一化：
- `casefold()` 大小写折叠
- 移除零宽字符（U+200B/200C/200D/FEFF/00AD）
- 移除 ASCII 空白（让 "六 四" 也能命中 "六四"）

**未实现**拼音/同形异构字归一化——那是无底洞，且误报会爆炸。这层定位是**绊线**，不是对抗"研究型对手"的纵深防御。

### 日志

命中只记录类别和 SHA-256 前 12 位哈希，**不记录原文**。这是因为日志文件本身可能成为合规风险。日志条目示例：

```
WARNING quickquip.common.sensitive_filter sensitive_filter[input] blocked scope=12345 hits=fraud:a1b2c3d4e5f6,gambling:9876fedcba01
```

要查具体词，需要本地对照 `config/sensitive_words.toml` 自行计算哈希。

## 部署步骤

### 1. 复制模板

```bash
cp config/sensitive_words.toml.example config/sensitive_words.toml
```

模板中只包含通用反诈/反垃圾词（杀猪盘、跑分平台、伪造证件等），**无政治、宗教、暴力、色情类**——这些维度需要部署者根据所在司法辖区自行填充。

### 2. 填充 17 类高风险场景

国内大模型备案要求覆盖 17 类高风险内容（见《生成式人工智能服务安全基本要求》）。建议按下表骨架组织：

| 类别 | 匹配模式 | 起步示例方向 |
|---|---|---|
| `political_leaders` | 上下文敏感（需搭配攻击性动词） | 现任领导人姓名 + 倒台/暗杀/讽刺等 |
| `political_events` | 绝对词 | 历史敏感事件名称及其变体 |
| `territorial` | 绝对词 | 领土主权类表述 |
| `ethnic_religion` | 绝对词 | 民族宗教（敏感方向） |
| `banned_organizations` | 绝对词 | 被禁组织、邪教名称 |
| `separatism` | 绝对词 | "X 独"模板很稳 |
| `violence_terror` | 绝对词 | 暴恐组织名 + 招募/加入 |
| `obscenity_minor` | 绝对词 | 涉未成年人色情 |
| `obscenity_explicit` | 绝对词 | 露骨色情词 |
| `drugs` | 绝对词 + 价格/出售 | 毒品名称 + 交易动词 |
| `weapons` | 绝对词 | 自制武器、改装枪等 |
| `fraud` | 绝对词 | 诈骗教程类 |
| `gambling` | 绝对词 | 赌博平台/教程 |
| `hate_speech` | 上下文敏感 | 仇恨言论（建议交给 LLM 后处理而非词表） |
| `suicide_promotion` | 绝对词 | 自杀教程/诱导 |
| `private_info_doxxing` | 绝对词 | 人肉搜索类 |
| `discrimination` | 上下文敏感 | 歧视言论 |

**起步建议**（最小集，约 50-80 词）：
1. 先填 `banned_organizations`、`separatism`、`violence_terror`——这三类几乎全是绝对词，零误伤
2. 再补 `weapons`、`fraud`、`gambling`——商业判定明确
3. 最后做 `political_leaders`、`political_events`——最容易误伤，优先用上下文匹配
4. `hate_speech`、`discrimination`——建议交给 LLM 后处理，词表无法覆盖语境

### 3. 词表来源

不要硬抄完整商业词表（误伤率极高）。建议综合：

- **GitHub 开源词表**：起步快，但需人工筛选
- **观察 LLM 拒答记录**：你的 LLM 提供商每次返回 `Content Exists Risk` / 安全警告，都是免费的标注数据
- **阿里云/腾讯云内容安全 API**：覆盖更全但增加延迟和成本，对群聊 bot 而言 overkill
- **测试群跑半个月，记录所有模型主动拒答**——这是质量最高的源

### 4. 重载与状态查看

修改 `config/sensitive_words.toml` 后，调用 `reload_filter()` 即可热更新（不需要重启 bot）。当前没有独立的群内重载命令；在服务器本地更新词表后，可执行 `/llm reload` 或重启 bot。

Web Admin 提供只读状态接口 `GET /ops/api/sensitive-filter/status`，返回配置文件是否存在、是否已加载以及 block/soft/total 计数。它不会返回词表内容、分类明细或文件路径。群内 `/llm health verbose` 也会展示 `sensitive_filter` 健康项，但不会回显词表路径。

## 接入点

文件：`quickquip/llm/service.py` `_generate_reply_for_scope()` 和 `quickquip/llm/tool_loop.py` `run_tool_call_loop()`

| 接入点 | 位置 | 行为 |
|---|---|---|
| 输入侧 | prompt 准备好之后、调用 LLM 之前 | block → 返回 `DEFAULT_BLOCK_REPLY`，不调 LLM |
| 历史侧 | `list_recent_conversation_messages()` 取出后、注入 LLM 前 | block → `content`/`raw_content` 用 `[内容已屏蔽]` 替换，不修改数据库 |
| 输出侧 | LLM 响应取出后、写入 store 前 | block → 替换为 `DEFAULT_OUTPUT_FALLBACK`，写入历史的也是替换后的 |
| **工具参数** | `tool_registry.execute()` 调用前 | block → 直接拒绝执行，返回错误 result，节省 token + 防止外部 API 收到违规查询 |
| **工具结果** | `tool_registry.execute()` 返回后 | block 命中 ≤ 5 个且原文 ≥ 200 字 → scrub；否则整体替换为占位文本，并标记 `is_error=True`（让 LLM 知道结果不完整） |

**为什么工具结果扫描尤其重要**：搜索/抓取类工具（`search_web`、`fetch`、各类 MCP 工具）从外部源拉取内容，**用户的查询可以引导但我们无法预先审查**。一段富集敏感词的 tool_result 会作为 messages 的一部分进入下一轮 provider 请求，正是触发 DeepSeek `Content Exists Risk` / Aliyun `Content security warning` 的高危场景。

**没有接入的位置**：
- `daily_summary` / `daily_briefing` 会走独立的模型级联 provider 调用，不经过 `LLMService.generate_reply()` 主链路，因此当前不会复用输入/输出/历史侧过滤器；如需加固，应在 `quickquip/llm/summarize.py` 与 `quickquip/llm/briefing.py` 的请求和响应边界接入同一个 `get_filter()`
- `wordcloud` 不调用 LLM，只读取群聊消息并渲染词频图片；如需避免敏感词出现在图片中，应在 `quickquip/chat/wordcloud.py` 的分词或渲染前增加扫描/剔除

## 性能

- 词表 ~1000 词，单条群聊消息（< 200 字符）扫描时间 < 0.5ms
- 词表 ~5000 词，扫描时间 < 1ms
- 自动机构建是一次性的（启动时或 `reload_filter()` 时），构建本身约 10-50ms

如果词表规模超过 50k，应当切换到 `pyahocorasick` C 扩展。当前实现保留了相同的接口，切换只需改 `_AhoCorasick` 类的实现。

## 不要做的事

- ❌ 把 `config/sensitive_words.toml` 提交到公开仓库
- ❌ 通过 Web Admin 或任何浏览器页面读取、回显、编辑 `config/sensitive_words.toml`
- ❌ 把命中日志记得太详细（如完整原文 + 用户 ID + 时间）——日志本身会成为合规风险
- ❌ 在群里**告知用户**触发了过滤——直接静默 + 后台日志即可，告知等于教用户绕过
- ❌ 让 LLM 自己判断"这内容能不能发"——增加成本和延迟，且模型自己也不可靠
- ❌ 试图覆盖拼音、谐音、同形字等所有变体——误报会爆炸，得不偿失

## 测试

```bash
pytest tests/unit/common/test_sensitive_filter.py
```
