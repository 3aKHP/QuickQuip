# QuickQuip 私聊指令速查

这是一份私聊场景下的简明指令教程。

如果你只想记最常用的几条，先看下面这 5 个：

- `/start_session`
- `/end_session`
- `/sessions`
- `/defectify 文字或图片`
- `/search 关键词`

---

## 1. 私聊 AI 是怎么工作的

和群聊不同，私聊 AI 需要先**开启会话**才能使用。

开启后，你发的所有普通消息（文字、图片、引用回复）都会自动进入 AI，不需要 `/ai` 或 `@机器人`。

如果你是引用一条旧消息后继续追问，机器人会把**当前提问者**和**被引用内容**分开理解；如果引用里还有合并转发，也会尽量读取其中的正文和图片。

关闭会话后，AI 不再响应，对话会被自动存档。

---

## 2. 会话管理

### 2.1 开启会话

```text
/start_session
```

开启后，之后发的消息都会进入 AI。

带附加设定开启（用于临时调整 AI 行为）：

```text
/start_session --preset "请用英文回复"
```

从存档恢复并开启：

```text
/start_session --resume
```

恢复指定编号的存档：

```text
/start_session --resume 3
```

也可以同时指定设定和恢复：

```text
/start_session --resume 3 --preset "继续用正式语气"
```

> `/llm on` 在私聊中与 `/start_session` 等价，同样支持 `--preset` 和 `--resume`。

### 2.2 结束会话

```text
/end_session
```

会话结束后对话自动存档，可以之后恢复。

如果不想保留存档：

```text
/end_session --no-save
```

> `/llm off` 在私聊中与 `/end_session` 等价，同样支持 `--no-save`。

### 2.3 恢复存档

恢复最近一次存档：

```text
/resume_session
```

恢复指定编号的存档：

```text
/resume_session 3
```

### 2.4 查看所有存档

```text
/sessions
```

列出你的所有历史存档（编号、消息条数、人格、创建时间）。

### 2.5 删除存档

```text
/delete_session 3
```

按编号删除指定存档，不可恢复。

---

## 3. AI 配置

私聊中你可以自行管理 AI 的所有配置，不需要管理员权限。

### 3.1 查看 AI 状态

```text
/llm status
```

查看会话是否开启、当前模型等基本信息。

### 3.2 查看详细配置

```text
/llm current
```

显示：

- 会话是否开启
- 记忆注入是否开启
- 当前 provider / model / persona
- 当前短期上下文条数
- 当前长期记忆条数

### 3.3 切换模型

```text
/llm use gemini-main gemini-3-flash-preview
```

### 3.4 查看可用模型

```text
/llm providers
```

```text
/llm models
```

```text
/llm models gemini-main
```

### 3.5 切换人格

```text
/llm persona use quickquip-default
```

### 3.6 查看可用人格

```text
/llm personas
```

### 3.7 改触发前缀

```text
/llm trigger prefix /bot
```

开关前缀触发：

```text
/llm trigger prefix_mode on
```

```text
/llm trigger prefix_mode off
```

> 注意：`/llm trigger at` 仅在群聊中有效，私聊不支持。

### 3.8 设置上下文读取上限

```text
/llm context_limit 20
```

重置为默认值：

```text
/llm context_limit reset
```

### 3.9 清空短期上下文

```text
/llm clear_context
```

清掉 AI 最近几轮对话，适合"串台"或"记错上下文"时用。

### 3.10 从上下文中删除指定消息

回复一条消息并发送：

```text
/llm delete_msg
```

或者手动指定消息 ID：

```text
/llm delete_msg 123456
```

### 3.11 重载配置

```text
/llm reload
```

重载同时会重置你的上下文条数覆盖（如有）。

### 3.12 查看 MCP 连接状态

```text
/llm mcp
```

### 3.13 查看 AI 健康状态

```text
/llm health
```

查看当前 AI 各 provider 的健康概况。想看逐项细节可以加参数：

```text
/llm health verbose
```

---

## 4. 记忆管理

私聊中你可以自行管理自己的长期记忆。

### 4.1 添加记忆

```text
/remember 我喜欢简短的回复
```

### 4.2 查看记忆

```text
/memories
```

按关键词筛选：

```text
/memories 回复
```

### 4.3 删除记忆

```text
/forget 回复
```

删除所有匹配关键词的记忆。

### 4.4 清空全部记忆

```text
/forget_all
```

---

## 5. 联网搜索

```text
/search 明日方舟终末地
```

```text
/search news Gemini 最新更新
```

```text
/search finance 英伟达股价
```

搜索在私聊中同样可用，用法和群聊一致。

---

## 6. 故障机器人转写

这是一个独立命令，不依赖当前私聊会话是否开启。

### 6.1 直接转写文字

```text
/defectify 这句话太抽象了
```

也支持中文别名：

```text
/故障化 这句话太抽象了
```

### 6.2 带图转写

```text
/defectify
```

然后直接附图即可。

### 6.3 引用消息后转写

先引用一条消息，再发送：

```text
/defectify
```

如果引用内容里有图片，也会一起参与转写。

输出结构固定为：

- 第一行：五字结果
- 第二行：`笑点解析：......。令人忍俊不禁。`

---

## 7. 尖塔化公式回复

《杀戮尖塔》梗的显式命令版：把输入内容提炼成一张语义上最接近的卡牌/遗物名，回复一句「<名字>了」。和 `/defectify` 一样是独立命令，不依赖当前私聊会话是否开启。

### 7.1 直接尖塔化文字

```text
/turmfluch 这句话太抽象了
```

### 7.2 带图 / 引用后尖塔化

```text
/turmfluch
```

然后直接附图即可，或先引用一条消息再发送；引用内容里的图片也会一起参与。

机器人固定只回一句话，例如「壁垒了」。当前没有中文别名；该命令走独立限流，触发过于频繁时会提示稍后再试。

---

## 8. 私聊 vs 群聊区别速览

| 功能 | 群聊 | 私聊 |
|------|------|------|
| 触发 AI | 需要 `/ai` 或 `@机器人` | 开启会话后自动响应 |
| 会话管理 | 无（始终共享群上下文） | 独立会话，支持存档/恢复 |
| AI 配置修改 | 仅管理员 | 任何人 |
| 记忆管理 | 仅管理员 | 任何人 |
| `/stats`、`/rules` | 可用 | 不可用 |
| `/tieba` 系列命令 | 可用 | 不可用 |
| `/disable`、`/enable` | 可用（管理员） | 不可用 |

---

## 9. 常见问题

### 9.1 为什么我发消息 AI 不理我

检查会话是否已开启：

```text
/llm status
```

如果显示"未开启"，先执行 `/start_session`。

### 9.2 怎么换个话题但不丢掉之前的对话

先结束当前会话（自动存档）：

```text
/end_session
```

再开启新会话：

```text
/start_session
```

以后想回到之前的话题时：

```text
/resume_session
```

### 9.3 怎么让 AI 临时换一种风格

用 `--preset` 指定临时设定：

```text
/start_session --preset "请用英文回复，语气正式"
```

这不会影响你的全局人格设置，仅对当前会话生效。

### 9.4 为什么 AI 回得很怪

先检查当前配置：

```text
/llm current
```

如果怀疑上下文有问题：

```text
/llm clear_context
```

---

## 10. 一页版速记

会话管理：

- `/start_session` — 开启会话
- `/start_session --preset "设定"` — 带设定开启
- `/start_session --resume [N]` — 从存档恢复
- `/end_session` — 结束并存档
- `/end_session --no-save` — 结束不存档
- `/resume_session [N]` — 恢复存档
- `/sessions` — 列出所有存档
- `/delete_session <N>` — 删除存档
- `/defectify <内容>` — 故障机器人转写
- `/turmfluch <内容>` — 尖塔化「xxx了」

AI 配置：

- `/llm status` — 查看状态
- `/llm current` — 查看详细配置
- `/llm use <provider> <model>` — 切换模型
- `/llm persona use <id>` — 切换人格
- `/llm context_limit <n>` — 设置上下文上限
- `/llm clear_context` — 清空上下文
- `/llm delete_msg` — 删除指定上下文消息
- `/llm reload` — 重载配置
- `/llm mcp` — 查看 MCP 状态
- `/llm health [verbose]` — 查看 AI 健康状态

记忆：

- `/remember <内容>` — 添加记忆
- `/memories [关键词]` — 查看记忆
- `/forget <关键词>` — 删除记忆
- `/forget_all` — 清空全部记忆

搜索：

- `/search [general|news|finance] <关键词>` — 联网搜索

如果只记一句话：

**想和 AI 私聊，先 `/start_session`。聊完了 `/end_session`。**
