# QuickQuip 私聊指令速查

私聊使用 AI 前需要先开启会话；开启后你发的普通消息（文字、图片、引用回复）会直接进入 AI，不需要 `/ai` 前缀或 @机器人。会话可以存档、恢复和删除；配置与记忆由你自己管理，不需要管理员权限。

只想用起来的话，会这三条就够了：

| 想做什么 | 发这条 |
|------|------|
| 开始和 AI 聊天 | `/start_session`，之后正常发消息就行 |
| 聊完了 | `/end_session`，对话自动存档 |
| 续上之前聊过的 | `/resume_session`，恢复最近一次存档 |

---

## 1. 会话生命周期

表格里的写法：`<尖括号>` 表示要换成你自己的内容，`[方括号]` 表示可以省略，斜杠分隔（如 on / off）表示任选其一。

| 命令 | 说明 |
|------|------|
| `/start_session` | 开启会话；此后普通消息自动进入 AI |
| `/end_session` | 结束会话并自动存档 |
| `/resume_session [N]` | 恢复存档；不带编号恢复最近一次，编号用 `/sessions` 查看 |
| `/sessions` | 列出全部存档（编号、消息条数、人格、创建时间） |
| `/delete_session N` | 删除指定编号的存档，不可恢复 |

参数与等价写法：

- `/start_session --preset "请用英文回复"` 带附加设定开启，仅对当前会话生效，不影响全局人格；`--resume [N]` 从存档恢复后开启。两者可组合：`/start_session --resume 3 --preset "继续用正式语气"`。
- `/end_session --no-save` 结束会话但不保留存档。
- `/llm on`、`/llm off` 在私聊中分别等价于 `/start_session`、`/end_session`，支持相同参数。
- `/start_sesssion`（三连 s）是历史注册拼写，同样有效。

会话行为补充：

- 引用一条消息追问时，当前提问与被引用内容会分开理解；引用里的合并转发会尽量读取其中的正文（转发中的图片不再附带原图，非视觉模型下以文字图注形式进入）。
- 上下文由会话纪元自动管理：AI 能回看的对话窗口随会话增长（默认上限约 6.4 万 token，冷场后自动收缩）；用 `/llm context_limit <n>` 可把本会话改为固定保留最新 n 条（上限 1024），`reset` 恢复自动管理。

---

## 2. AI 配置（`/llm`）

provider 指 AI 的服务来源（如 Gemini、OpenAI），一个 provider 下有多个模型；persona（人格）决定 AI 的说话风格。

查询类子命令任何人可用：

| 子命令 | 说明 |
|------|------|
| `/llm status` | 会话是否开启、当前模型等基本信息（`/llm` 不带参数同此） |
| `/llm current` | 详细配置：当前 provider / 模型 / 人格、记忆与上下文条数 |
| `/llm health [verbose]` | 各 provider 健康概况；加 `verbose`（或 `detail`、`full`）看逐项细节 |
| `/llm providers`、`/llm models [provider]` | 列出可用的模型来源与其下模型 |
| `/llm personas` | 列出可用人格 |
| `/llm memory status` | 记忆注入与长期记忆概况 |
| `/llm mcp` | 外部工具（MCP）连接状态（`mcp status` 同此） |

改动类子命令私聊中任何人可用（群聊中仅管理员）：

| 子命令 | 说明 |
|------|------|
| `/llm use <provider> [model]` | 切换模型；名称先用 `/llm providers`、`/llm models` 查 |
| `/llm persona use <人格ID>` | 切换人格；可用 `/llm personas` 查 |
| `/llm trigger prefix <前缀>` | 修改触发前缀（默认 `/ai`） |
| `/llm trigger prefix_mode on / off` | 开关前缀触发 |
| `/llm memory on / off` | 开关记忆注入 |
| `/llm auto_memory on / off / reset / status` | 自动记忆抽取的开关、重置为全局默认、查看 |
| `/llm context_limit <条数>`（`reset` 或 `off` 恢复默认） | 把本会话改为固定保留最新 n 条（上限 1024；默认由会话纪元自动管理） |
| `/llm clear_context` | 清空短期上下文，“串台”或记错上下文时用 |
| `/llm delete_msg` | 引用一条消息发送本命令，或 `/llm delete_msg <消息ID>`，从上下文删除该条 |
| `/llm reload` | 重载全局 LLM 配置，并重置你的上下文条数覆盖 |
| `/llm probe` | 并发探活所有 provider |
| `/llm mcp reload` | 拉取 MCP 镜像并重连 |

两点注意：`/llm trigger at` 仅群聊有效，私聊只支持前缀触发；`/llm reload` 与 `/llm probe` 虽然私聊任何人可执行，但作用于全局运行时——reload 之后的探活会发一条真实请求，可能产生 provider 计费。

---

## 3. 记忆管理

长期记忆是跨会话保留的笔记，AI 每次回复时都会参考（即“记忆注入”）。

| 命令 | 说明 |
|------|------|
| `/remember <内容>` | 添加一条长期记忆 |
| `/memories [关键词]` | 列出，或按关键词筛选记忆 |
| `/forget <关键词>` | 删除所有匹配关键词的记忆 |
| `/forget_all` | 清空全部记忆 |

---

## 4. 私聊也可用的共享命令

以下命令群聊、私聊用法一致，详见[群聊指令速查](group-commands.md)：

- `/search [general / news / finance] <关键词>` — 联网搜索
- `/defectify <内容>`（别名 `/故障化`）— 故障机器人转写（尖塔角色 Defect 梗）；独立命令，不依赖会话是否开启，输出固定为五字结果加一行笑点解析
- `/turmfluch <内容>` — 尖塔化“xxx了”；同样不依赖会话，无中文别名，用得太频繁会提示稍后再试
- `/draw`、`/tts`、`/music` — 图片 / 语音 / 音乐生成
- `/roll`、`/choose`、`/fortune`、`/vote` — 骰子、随机选择、每日运势、发起投票

牛牛的三张全局榜（`牛牛长度总排行`、`牛牛深度总排行`、`牛牛绝对值总排行`，可带条数参数）私聊也可查询，详见[群内游戏指南](group-games.md)。`/reload_rules` 与 `/reload_personas`（重新加载文字规则与人格词表，通常在修改配置文件后使用）私聊同样可用。

---

## 5. 私聊与群聊的区别

| 功能 | 群聊 | 私聊 |
|------|------|------|
| 触发 AI | `/ai` 前缀或 @机器人（需规则开启） | 开启会话后自动响应 |
| 会话与上下文 | 共享群上下文，无会话开关 | 独立会话，支持存档与恢复 |
| AI 配置修改 | 仅管理员 | 任何人 |
| 记忆管理 | 仅管理员 | 任何人 |
| `/stats`、`/rules` | 可用 | 不可用 |
| `/tieba` 系列 | 可用 | 不可用 |
| `/disable`、`/enable` | 可用（管理员） | 不可用 |
| `/wordcloud` | 可用（管理员） | 不可用 |

---

## 6. 常见问题

**发消息 AI 不理我？** 先 `/llm status` 确认会话已开启；未开启则 `/start_session`。

**回复很怪、像“串台”了？** `/llm current` 检查当前配置，`/llm clear_context` 清空短期上下文；仍不正常可用 `/llm delete_msg` 移除具体某条有问题的消息。
