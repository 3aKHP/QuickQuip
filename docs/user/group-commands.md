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

### 2.3 引用消息或合并转发后提问

可以先引用一条群消息，再触发 AI：

```text
@机器人 这句话是谁说的？
```

或者：

```text
/ai 你怎么看这段？
```

当前实现会把**当前提问者**和**被引用者**分开理解，不会默认把引用里的那个人当成正在提问的人。

如果你引用的是一条**合并转发消息**，机器人也会尽量读取其中的正文和图片，而不只是看见一个“合并转发消息”的外壳。

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

### 5.10 轻娱乐命令

#### 5.10.1 掷骰子

```text
/roll
```

默认掷一个 6 面骰子。也可以指定数量和面数：

```text
/roll 2d6
```

```text
/roll d20
```

骰子数量范围 1-10，面数范围 2-1000。

#### 5.10.2 随机选择

```text
/choose 原神 星铁 绝区零
```

从多个选项中随机选一个。选项可以用引号包裹（含空格的选项）：

```text
/choose "去打游戏" "去睡觉" "继续干活"
```

#### 5.10.3 每日运势

```text
/fortune
```

基于你的 QQ 号和当天日期生成运势（大吉 / 吉 / 中吉 等），带有对应描述。同一个人同一天多次执行结果相同。

#### 5.10.4 发起投票

```text
/vote "晚上吃什么" 火锅 烧烤 日料
```

创建一个多选项投票。议题需要用引号包裹，选项之间用空格分隔，最多 9 个选项。

### 5.11 语录收藏

#### 5.11.1 收藏语录

回复一条消息并发送：

```text
/quote
```

即可将该消息收藏为本群语录。

#### 5.11.2 随机查看

```text
/quote
```

```text
/quote random
```

随机展示一条已收藏的语录，附带语录编号。

#### 5.11.3 按编号查看

```text
/quote 5
```

```text
/quote #5
```

查看编号为 5 的语录。编号按群内收藏顺序分配，删除不影响已有编号。

#### 5.11.4 搜索语录

```text
/quote search 关键词
```

```text
/quote s 关键词
```

搜索包含指定关键词的语录，最多显示 10 条匹配结果，每条附带编号。

### 5.12 搜索群聊记录

```text
/find 关键词
```

在最近 30 天的群聊记录中搜索指定关键词，最多展示 5 条匹配结果。

### 5.13 离线留言

#### 5.13.1 留言给某人

```text
/tell @某人 明天记得带书
```

当目标群友下次在群里发言时，机器人会把这条留言转达给 ta。

#### 5.13.2 查看待收留言

```text
/tells
```

列出所有等待投递给你的离线留言。

#### 5.13.3 撤回留言

```text
/untell
```

撤回你发出的最近一条尚未投递的离线留言。

### 5.14 生成词云

```text
/wordcloud
```

生成当天群聊的词云图片（仅限管理员）。也支持指定时间范围：

```text
/wordcloud week
```

```text
/wordcloud month
```

也支持中文别名：

```text
/词云 month
```

### 5.15 随机搬运贴吧帖子

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

### 5.16 AI 图片生成

```text
/draw 一只在喝奶茶的猫
```

也支持指定模型和参数：

```text
/draw openai-dalle3 一只在喝奶茶的猫
```

```text
/draw --size 1024x1024 --quality high 未来城市
```

可以引用一张图片后发送 `/draw`，以图生图。

### 5.17 文字转语音

```text
/tts 你好世界
```

查看可用模型：

```text
/tts models
```

查看可用音色：

```text
/tts voices
```

```text
/tts voices gemini-tts 温柔
```

指定音色生成：

```text
/tts --voice 音色ID 你好世界
```

### 5.18 AI 写歌

```text
/music 流行 关于夏天的歌
```

只写歌词不生成音频：

```text
/music lyrics --title "夏日" 关于夏天和友情的歌
```

修改已有歌词：

```text
/music lyrics edit --title "夏日" --lyrics "原歌词" 把副歌改得更激昂
```

查看可用模型：

```text
/music models
```

### 5.19 每日群聊播报

机器人可以收集群聊数据，按早/午/晚报三个时段生成群聊动态简报。该功能默认关闭，需要管理员手动开启。

#### 开启 / 关闭

```text
/briefing on
```

```text
/briefing off
```

#### 查看状态

```text
/briefing status
```

#### 立即生成

```text
/briefing now
```

默认生成时段为当前时间匹配的时段，也可指定：

```text
/briefing now morning
```

```text
/briefing now noon
```

```text
/briefing now evening
```

如果当前模型输出异常中断，机器人会自动尝试级联里的下一个播报模型，不会直接把半截午报发出来。

### 5.20 群内小游戏

QuickQuip 内置 4 款群内游戏，详见 [群内游戏指南](group-games.md)。以下是命令速查：

#### Session 型游戏（`/game` 入口）

| 游戏 | 发起 | 玩法 |
|------|------|------|
| 数字炸弹 | `/game start 数字炸弹` | 猜 1-1000 |
| 21 点 | `/game start 21点 <赌注>` | 入场→开局→拿牌/停牌 |
| 俄罗斯轮盘 | `/game start 俄罗斯轮盘 <赌注>` | 选子弹→接受对决→开枪 |

通用命令：

```text
/game list              — 查看可玩游戏
/game stop              — 强制结束当前游戏
/game score <游戏名>     — 查看游戏排行
```

#### 牛牛大作战（持久 RPG，独立命令）

| 命令 | 说明 |
|------|------|
| `注册牛牛` | 创建牛牛（随机初始长度） |
| `注销牛牛` | 删除牛牛（花费 500 金币） |
| `打胶` | 随机事件改变长度（CD 180s） |
| `击剑 @某人` | 1v1 对战转移长度（CD 180s） |
| `打胶运势` | 查看今日打胶运势值及评价 |
| `击剑运势` | 查看今日击剑运势值及评价 |
| `我的牛牛` | 查看状态、排名、双运势、评价 |
| `我的牛牛战绩 [N]` | 查看最近操作记录（默认 10 条） |
| `牛牛总排行 [N]` | 自然数值排行（有符号排序） |
| `牛牛绝对值排行 [N]` | 绝对值排行（忽略正负号） |
| `牛牛绝对值总排行 [N]` | 全局绝对值排行 |
| `牛牛长度排行 [N]` | 正数群体排行 |
| `牛牛长度总排行 [N]` | 全局正数排行 |
| `牛牛深度排行 [N]` | 负数群体排行 |
| `牛牛深度总排行 [N]` | 全局负数排行 |
| `/牛牛文案` | 查看当前文案模式及可用模式列表 |
| `/牛牛文案 <模式名>` | 切换本群文案模式（管理员） |

#### 金币系统

| 命令 | 说明 |
|------|------|
| `/sign` / `/签到` | 每日签到 |
| `/gold` / `/金币` | 查看余额 |
| `/gold_rank` / `/金币排行` | 金币排行 |

### 5.21 生成人物志

```text
/profile @某人
```

默认生成中版人物志。也可以指定长度：

```text
/profile short @某人
```

```text
/profile middle @某人
```

```text
/profile long @某人
```

```text
/profile full @某人
```

`short` 接近旧版短评，`middle` 是默认长文，`long` 会使用更多发言样本，`full` 会尽量读取该群已记录的完整发言。

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

### 6.15 热重载规则和人格

重载聊天规则（`chat_rules.toml`）：

```text
/reload_rules
```

重载 LLM 人格（`personas/` 目录）：

```text
/reload_personas
```

适合在通过 Web Admin 在线编辑配置文件后立即生效。

### 6.16 立即同步贴吧缓存

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
按部署指南完成贴吧登录态导出。
```

### 6.17 贴吧实时抓取

```text
/tieba_peek 搬石
```

从指定贴吧立即抓取一条随机帖子，绕过贴吧缓存池。

---

## 7. 语音输入与节日

### 7.1 语音消息转文字

机器人支持语音消息识别。群聊中发送语音时，需要同时 `/ai` 或 `@机器人` 触发。语音消息会被自动转写为文字注入 AI 上下文，也会进入每日词云和消息统计。

如果语音消息本身已带有文本转录（由协议端提供），机器人会优先使用该文本。

### 7.2 节日自动问候

机器人在特定传统节日（元旦、春节、元宵节、端午节、中秋节、除夕）会自动调整语气并向群内发送节日问候。节日的日期基于公历和农历计算，无需人工配置。

---

## 8. 你可以怎么理解”记忆”

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

## 9. 常见问题

### 9.1 为什么我发了消息 AI 不理我

先检查你是不是用了：

- `/ai`
- `@机器人`

如果都没有，那大概率不会触发 AI。

### 9.2 为什么 AI 看起来没记住我手动加的记忆

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

### 9.3 为什么 AI 回得很怪

可以先试：

```text
/llm current
```

看看当前模型是不是你想要的那个。

如果怀疑上下文串了，可以让管理员执行：

```text
/llm clear_context
```

### 9.4 为什么搜索不到最新东西

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

## 10. 一页版速记

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
- `/roll [NdM]` — 掷骰子
- `/choose A B C` — 随机选择
- `/fortune` — 每日运势
- `/vote "议题" 选项...` — 发起投票
- `/quote` — 收藏语录 / 随机一条
- `/quote N` — 查看编号为 N 的语录
- `/quote search 关键词` — 搜索语录
- `/quote random` — 随机语录
- `/find 关键词` — 搜索群聊记录
- `/tell @某人 内容` — 离线留言
- `/tells` — 查看待收留言
- `/untell` — 撤回留言
- `/wordcloud [today|week|month]` — 生成词云（管理员）
- `/draw 描述` — AI 图片生成
- `/tts 文本` — 文字转语音
- `/music 风格 主题` — AI 写歌
- `/profile [short|middle|long|full] @某人` — 生成人物志
- `/tieba`
- `/tieba [贴吧名]`
- `/tieba text [贴吧名]`
- `/tieba status [贴吧名]`
- `/tieba source [贴吧名]`
- `/sign` — 每日签到
- `/gold` — 查看金币
- `/gold_rank` — 金币排行
- `/game list` — 查看可玩游戏
- `/game start 数字炸弹` — 数字炸弹
- `/game start 21点 <赌注>` — 21 点
- `/game start 俄罗斯轮盘 <赌注>` — 俄罗斯轮盘
- `/game stop`
- `/game score <游戏名>` — 游戏排行
- `注册牛牛` — 创建牛牛
- `注销牛牛` — 删除牛牛
- `打胶` / `击剑 @某人` — 牛牛操作
- `我的牛牛` / `我的牛牛战绩 [N]` — 查看状态
- `牛牛总排行 [N]` — 自然数值排行
- `牛牛绝对值排行 [N]` — 绝对值排行
- `牛牛长度排行 [N]` / `牛牛深度排行 [N]` — 正/负群体排行
- `/牛牛文案 [模式名]` — 查看或切换文案模式
- `/briefing status` — 查看播报状态

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
- `/reload_rules` — 热重载聊天规则
- `/reload_personas` — 热重载 LLM 人格
- `/reset_stats`
- `/tieba refresh [贴吧名|all]`
- `/tieba_peek <贴吧名>` — 实时抓取帖子
- `/summary on|off|status|now`
- `/briefing on|off|status|now [morning|noon|evening]`

如果只记一句话：

**想让 AI 回你，就用 `/ai` 或 `@机器人`。想查最新信息，就用 `/search`。**

---

## 11. 每日群聊总结

机器人可以收集当天的群聊，每天早上六点自动生成一篇约 2000 字的小作文风格日报，并在中午十二点发到群里。该功能默认关闭，需要管理员手动开启。

### 11.1 开启 / 关闭

```text
/summary on
```

```text
/summary off
```

### 11.2 查看状态

```text
/summary status
```

### 11.3 立即生成

```text
/summary now
```

会生成前一天 06:00 至当前时刻的总结，直接发到群里，不存档。每分钟限一次。
