# QuickQuip 群内指令速查

这是一份给群友看的简明版教程。

如果你只想记最常用的几条，先看下面这 6 个：

- `/ai 你的问题`
- `@机器人 你的问题`
- `/search 关键词`
- `/defectify 文字或图片`
- `/tieba`
- `/stats`
- `/rules`

---

## 1. 机器人平时怎么触发

QuickQuip 现在有两类能力：

- 旧的规则回复
  - 例如复读、彩蛋、时区猜测
  - 这些不一定需要指令
- 新的 AI 回复
  - 需要你**明确触发**

AI 默认只在下面两种情况回复：

- 消息以 `/ai` 开头
- 消息里 `@机器人`

例如：

```text
/ai 你觉得今天适合熬夜吗
```

```text
@机器人 这句话是什么意思
```

如果只是普通聊天，AI 默认不会乱插话。

---

## 2. 最常用的 AI 用法

### 2.1 纯文字提问

```text
/ai 你怎么看这段发言
```

```text
@机器人 帮我总结一下刚刚的讨论
```

### 2.2 带图片提问

可以直接发：

```text
/ai 这张图里是什么
```

然后带一张图片。

也可以只发图片：

```text
/ai
```

然后带图。  
这时机器人会默认按“请描述这张图片”来理解。

也支持：

```text
@机器人 这图在表达什么
```

然后带图。

---

## 3. 联网搜索怎么用

### 3.1 普通搜索

```text
/search 明日方舟终末地
```

### 3.2 新闻搜索

```text
/search news Gemini 最新更新
```

### 3.3 财经搜索

```text
/search finance 英伟达股价
```

搜索结果会给出：

- 简短摘要
- 若干条结果链接

适合查：

- 最新新闻
- 官网资料
- 最近更新
- 时效性信息

---

## 4. 故障机器人转写

这是一个专门的抽象命名功能，会把输入内容转写成一个读音接近“故障机器人”的五字别名。

### 4.1 直接转写文字

```text
/defectify 这人又在群里复读了
```

也支持中文别名：

```text
/故障化 这人又在群里复读了
```

### 4.2 带图转写

```text
/defectify
```

然后直接附一张图。

### 4.3 引用消息后转写

可以先引用一条群消息，再发送：

```text
/defectify
```

如果引用消息里带图，也会一起参与转写。

### 4.4 输出长什么样

机器人会固定输出两段：

- 第一行：一个五字结果
- 第二行：`笑点解析：......。令人忍俊不禁。`

---

## 5. 普通成员可用命令

### 5.1 查看群统计

```text
/stats
```

查看本群消息量和规则触发情况。

### 5.2 查看规则开关

```text
/rules
```

查看本群哪些规则开着，哪些关着。

### 5.3 查看 AI 当前状态

```text
/llm status
```

看当前群 AI 是否开启、用的是哪个模型。

### 5.4 查看 AI 当前详细配置

```text
/llm current
```

会显示：

- AI 是否开启
- 记忆注入是否开启
- 当前 provider / model / persona
- 当前短期上下文条数
- 当前长期记忆条数

### 5.5 查看模型列表

```text
/llm providers
```

```text
/llm models
```

```text
/llm models gemini-main
```

### 5.6 查看人格列表

```text
/llm personas
```

### 5.7 查看记忆状态

```text
/llm memory status
```

### 5.8 查看 MCP 连接状态

```text
/llm mcp
```

查看当前 MCP（Model Context Protocol）连接是否正常。

### 5.9 查看已保存记忆

```text
/memories
```

或者按关键词筛：

```text
/memories 阿桃
```

### 5.10 随机搬运贴吧帖子

```text
/tieba
```

默认会从全部已配置贴吧来源里随机发一条缓存帖子，带标题、摘要、原帖链接和镇楼图。

如果想指定来源贴吧：

```text
/tieba 搬石
```

如果只想看文字版：

```text
/tieba text
```

也可以指定来源：

```text
/tieba text 搬石
```

查看当前贴吧缓存和同步状态：

```text
/tieba status
```

也可以只看某一个来源：

```text
/tieba status 搬石
```

查看已配置的来源池摘要：

```text
/tieba source
```

也可以只看某一个来源：

```text
/tieba source 搬石
```

---

## 6. 管理员可用命令

下面这些通常只有管理员 / 群主能改。

### 6.1 开关 AI

```text
/llm on
```

```text
/llm off
```

### 6.2 切换模型

```text
/llm use gemini-main gemini-3-flash-preview
```

```text
/llm use openai-main gpt-5.4
```

### 6.3 切换人格

```text
/llm persona use quickquip-default
```

### 6.4 改触发方式

改前缀：

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

开关艾特触发：

```text
/llm trigger at on
```

```text
/llm trigger at off
```

### 6.5 开关记忆注入

```text
/llm memory on
```

```text
/llm memory off
```

### 6.6 清空 AI 短期上下文

```text
/llm clear_context
```

这会清掉 AI 最近几轮对话上下文。
适合在 AI”串台”或”记错上下文”时用。

### 6.7 从上下文中删除指定消息

回复一条消息并发送：

```text
/llm delete_msg
```

或者手动指定消息 ID：

```text
/llm delete_msg 123456
```

适合在 AI 记住了不该记住的消息时用。

### 6.8 重载 AI 配置

```text
/llm reload
```

重载会同时重置本群的上下文条数覆盖（如有）。

### 6.9 手动添加记忆

```text
/remember 阿桃喜欢薄荷糖
```

### 6.10 删除记忆

```text
/forget 薄荷糖
```

### 6.11 清空本群全部长期记忆

```text
/forget_all
```

一次性清除本群所有已存的长期记忆。

### 6.12 设置上下文读取上限

```text
/llm context_limit 5
```

将本群每次调用 AI 时回溯的对话轮数上限设为 5 条（全局默认为 10）。
重启、`/llm clear_context` 均不影响此设置，直到显式重置或执行 `/llm reload`。

重置为全局默认：

```text
/llm context_limit reset
```

### 6.13 群规则开关

禁用某条旧规则：

```text
/disable divine_arrival
```

重新启用：

```text
/enable divine_arrival
```

### 6.14 重置群统计

```text
/reset_stats
```

### 6.15 立即同步贴吧缓存

```text
/tieba refresh
```

如果只同步某一个来源贴吧：

```text
/tieba refresh 搬石
```

如果想一次性同步全部来源，也可以显式写：

```text
/tieba refresh all
```

如果提示需要人工续签登录态，请在机器人所在机器上运行：

```text
python dev/tools/tieba_login.py
```

---

## 7. 你可以怎么理解“记忆”

QuickQuip 里的“记忆”分两种：

- 短期上下文
  - AI 最近几轮对话
  - 可以用 `/llm clear_context` 清掉
- 长期记忆
  - 手动 `/remember` 存进去的内容
  - 可以用 `/memories` 看
  - 可以用 `/forget` 删除

当前 AI **不会**把全天群聊都偷偷记下来。  
只有显式触发 AI 时，才会用到有限的上下文。

---

## 8. 常见问题

### 8.1 为什么我发了消息 AI 不理我

先检查你是不是用了：

- `/ai`
- `@机器人`

如果都没有，那大概率不会触发 AI。

### 8.2 为什么 AI 看起来没记住我手动加的记忆

先检查：

```text
/llm memory status
```

看“记忆注入”是不是开着。

再检查：

```text
/memories
```

看记忆是不是确实已经存进去。

### 8.3 为什么 AI 回得很怪

可以先试：

```text
/llm current
```

看看当前模型是不是你想要的那个。

如果怀疑上下文串了，可以让管理员执行：

```text
/llm clear_context
```

### 8.4 为什么搜索不到最新东西

试试把搜索词写得更明确：

```text
/search news OpenAI 最新模型
```

比单独搜：

```text
/search OpenAI
```

通常更准。

---

## 9. 一页版速记

普通成员最常用：

- `/ai 你的问题`
- `@机器人 你的问题`
- `/search 关键词`
- `/defectify 文字或图片`
- `/stats`
- `/rules`
- `/llm status`
- `/llm current`
- `/llm mcp`
- `/memories`
- `/tieba`
- `/tieba [贴吧名]`
- `/tieba text [贴吧名]`
- `/tieba status [贴吧名]`
- `/tieba source [贴吧名]`

管理员最常用：

- `/llm on`
- `/llm off`
- `/llm use <provider> <model>`
- `/llm persona use <id>`
- `/llm memory on`
- `/llm memory off`
- `/llm context_limit <n>`
- `/llm context_limit reset`
- `/llm clear_context`
- `/llm delete_msg`
- `/llm reload`
- `/remember <内容>`
- `/forget <关键词>`
- `/forget_all`
- `/disable <rule>`
- `/enable <rule>`
- `/tieba refresh [贴吧名|all]`
- `/summary on|off|status|now`

如果只记一句话：

**想让 AI 回你，就用 `/ai` 或 `@机器人`。想查最新信息，就用 `/search`。**

---

## 10. 每日群聊总结

机器人可以收集当天的群聊，每天早上六点自动生成一篇约 2000 字的小作文风格日报，并在中午十二点发到群里。该功能默认关闭，需要管理员手动开启。

### 10.1 开启 / 关闭

```text
/summary on
```

```text
/summary off
```

### 10.2 查看状态

```text
/summary status
```

### 10.3 立即生成

```text
/summary now
```

会生成前一天 06:00 至当前时刻的总结，直接发到群里，不存档。每分钟限一次。
