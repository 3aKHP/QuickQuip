# 从零开始学习正则表达式 —— 以 QuickQuip 项目为例

> **面向读者：** 零基础的 Python 初学者，希望通过真实项目案例理解正则表达式。
>
> **前置要求：** 了解基本的 Python 语法（字符串、函数调用）。
>
> **源码指引：** 本文引用的源码路径以 `src/quickquip/` 下的主实现为准。`src/plugins/` 目录是 NoneBot2 插件入口层，只做 re-export，不包含业务逻辑。文字规则配置在 `config/chat_rules.toml`（部署级私有，权威模板为 `config/chat_rules.toml.example`，由 `src/quickquip/chat/config.py` 加载），规则匹配引擎位于 `src/quickquip/chat/text_rules.py`。

---

## 目录

1. [什么是正则表达式？](#1-什么是正则表达式)
2. [Python 中的正则表达式工具箱](#2-python-中的正则表达式工具箱)
3. [基础语法速查](#3-基础语法速查)
4. [从简单到复杂：逐步拆解项目实例](#4-从简单到复杂逐步拆解项目实例)
5. [进阶特性详解](#5-进阶特性详解)
6. [现行规则体系：从一条正则到一条生效的规则](#6-现行规则体系从一条正则到一条生效的规则)
7. [项目中的正则表达式全景索引](#7-项目中的正则表达式全景索引)
8. [常见陷阱与调试技巧](#8-常见陷阱与调试技巧)
9. [练习题](#9-练习题)
10. [延伸资源](#10-延伸资源)

---

## 1. 什么是正则表达式？

**正则表达式**（Regular Expression，简称 regex 或 regexp）是一种用来描述“文本模式”的微型语言。你可以把它想象成一个**超级升级版的搜索功能**：

- 普通搜索：在文本中找“猫” → 只能精确匹配“猫”这个字
- 正则搜索：在文本中找“任意一个汉字重复两次后跟`你的`” → 能匹配“牛牛你的”“哈哈你的”“嘿嘿你的”……

在 QuickQuip 项目中，正则表达式是**规则引擎的核心**。机器人收到一条群聊消息后，会依次用多个正则表达式去“试探”这条消息是否匹配某个趣味回复规则。一旦匹配成功，就提取关键信息、填入模板、发送回复。

### 一个直观的例子

当群友发送 `玩原神玩的` 时，机器人会回复 `原神怎么你了`。这背后的正则表达式是：

```python
r"玩(?P<target>.+?)玩的"
```

它做了这些事：
1. 寻找以 `玩` 开头的文本
2. 捕获中间的内容（`原神`），并命名为 `target`
3. 确认以 `玩的` 结尾

这就是正则表达式的威力——用一条简短的规则，匹配无穷多种输入。

---

## 2. Python 中的正则表达式工具箱

Python 通过内置的 `re` 模块提供正则表达式支持。QuickQuip 项目中主要使用了以下函数：

### `re.search(pattern, string)`

在字符串的**任意位置**搜索第一个匹配项。

```python
import re

result = re.search(r"神临", "今天神临了")
if result:
    print("匹配成功！")  # ✅ 会执行
```

### `re.compile(pattern)`

将正则表达式**预编译**为一个 Pattern 对象，适合需要反复使用同一个正则的场景。

```python
import re

# 预编译——只解析一次正则语法，后续匹配更高效
GOOD_GIRL_START_PATTERN = re.compile(r"^(.+?)是好(.+?)吗[？?]*$")

# 使用 .fullmatch() 要求整个字符串完全匹配
result = GOOD_GIRL_START_PATTERN.fullmatch("小明是好学生吗？")
if result:
    print(result.group(1))  # "小明"
    print(result.group(2))  # "学生"
```

QuickQuip 的规则引擎在启动时把全部规则正则统一预编译进 `_COMPILED_PATTERNS`（`text_rules.py`），配置热重载时原地重建，见 §6.6。

### `re.sub(pattern, repl, string)`

用正则表达式做**查找替换**。项目中用它来替换模板中的 `$1`、`$2` 等占位符：

```python
import re

template = "还在$1"
# 将 $1 替换为正则捕获组的实际值
result = re.sub(r"\$(\d+)", lambda m: "打游戏", template)
print(result)  # "还在打游戏"
```

### 原始字符串前缀 `r"..."`

你会注意到项目中的正则表达式都以 `r` 开头。这是 Python 的**原始字符串**（raw string），它会阻止 Python 解释反斜杠转义：

```python
# 不用 r：\d 会被 Python 当作转义序列（虽然 \d 恰好不是有效转义，但 \b 就会出问题）
pattern1 = "\\d+"     # 需要双反斜杠
pattern2 = r"\d+"     # ✅ 推荐写法，所见即所得
```

**经验法则：写正则时永远用 `r"..."` 前缀。**

---

## 3. 基础语法速查

### 3.1 普通字符——字面匹配

最简单的正则就是普通文字，它们匹配自身：

```python
r"神临"      # 匹配文本中出现的“神临”二字
```

QuickQuip 中大量“梗触发”使用的就是这种简单匹配。现行配置里它长这样（TOML，摘自 `config/chat_rules.toml.example`）：

```toml
[[rules]]
name           = 'divine_arrival'
patterns       = ['神临', '降临']
reply_template = '{current_time}，@{sender_name} 区从天降'
rate_limit_key = 'divine_arrival'
priority       = 100
```

`patterns` 用 TOML 字面量字符串（单引号）：字面量字符串不处理转义序列，正则里的 `\1`、`一` 会原样传给 `re` 编译——等价于 Python 的 `r'...'`。若用双引号基本字符串，`一` 会被 TOML 转义成实际汉字（仍可用），但 `\1` 是非法转义会直接报解析错误，所以含反向引用的模式必须用单引号。任意一条 pattern 命中即触发。

### 3.2 锚点——限定匹配位置

| 符号 | 含义 | 示例 |
|------|------|------|
| `^` | 字符串**开头** | `^我` 匹配以“我”开头的文本 |
| `$` | 字符串**结尾** | `的$` 匹配以“的”结尾的文本 |

当 `^` 和 `$` 同时出现时，要求**整个字符串**完全符合模式：

```python
r"^我喜欢(.+)$"    # 整条消息必须是“我喜欢...”的格式
```

### 3.3 字符类——匹配一类字符

| 语法 | 含义 | 示例 |
|------|------|------|
| `[abc]` | 匹配 a、b 或 c 中的任意一个 | `[？?]` 匹配中文或英文问号 |
| `[a-z]` | 匹配 a 到 z 的任意小写字母 | |
| `[\u4e00-\u9fa5]` | 匹配任意一个**中文汉字** | 这是 Unicode 范围 |
| `.` | 匹配**任意字符**（换行符除外） | `玩.+?玩的` |
| `\d` | 匹配数字 `[0-9]` | `\$(\d+)` 匹配 `$1`、`$2` |
| `\s` | 匹配空白字符（空格、制表符等） | `[，,]\s*` |

项目中汉字范围 `[\u4e00-\u9fa5]` 出现了多次：

```python
# double_char_ni_de 规则：匹配两个相同汉字 + “你的”
r"^([\u4e00-\u9fa5])(\1)你的$"

# i_do 规则：匹配“我” + 两个汉字
r"^我(?P<verb>[\u4e00-\u9fa5]{2})[！!。，,？?]*$"
```

### 3.4 量词——控制重复次数

| 量词 | 含义 | 示例 |
|------|------|------|
| `*` | 0 次或多次 | `[？?]*` 匹配零个或多个问号 |
| `+` | 1 次或多次 | `.+` 匹配至少一个任意字符 |
| `?` | 0 次或 1 次 | `(?:的)?` 可选的“的” |
| `{n}` | 恰好 n 次 | `[\u4e00-\u9fa5]{2}` 恰好两个汉字 |
| `{n,m}` | n 到 m 次 | `.{2,}` 至少两个字符 |

#### 贪婪 vs 非贪婪

默认情况下，量词是**贪婪**的——尽可能多地匹配：

```python
r"玩(.+)玩的"   # 贪婪：输入“玩A玩B玩的”会匹配到“A玩B”
r"玩(.+?)玩的"  # 非贪婪（加 ?）：匹配到“A”就停止
```

在量词后加 `?` 可以切换为**非贪婪**模式。QuickQuip 中的 `play_target` 规则就使用了非贪婪匹配：

```python
r"玩(?P<target>.+?)玩的"
#                  ^^  非贪婪，匹配尽量短的内容
```

### 3.5 转义——匹配特殊字符

正则中有特殊含义的字符（如 `.`、`*`、`?`、`(`、`)`、`$` 等）需要用 `\` 转义才能匹配其字面值：

```python
r"\$(\d+)"     # 匹配 $ 符号后跟数字，如 $1、$23
"[？?]"       # 在字符类 [] 内，? 不需要转义
"[！!。，,？?]*"  # 匹配零个或多个中英文标点
```

---

## 4. 从简单到复杂：逐步拆解项目实例

下面按照从简单到复杂的顺序，逐一拆解 QuickQuip 规则集中每条正则的设计思路。示例均为现行 `config/chat_rules.toml.example` 中的真实配置。

### 4.1 纯文字匹配——`divine_arrival` 规则

```toml
[[rules]]
name           = 'divine_arrival'
patterns       = ['神临', '降临']
reply_template = '{current_time}，@{sender_name} 区从天降'
rate_limit_key = 'divine_arrival'
priority       = 100
```

**正则分析：** `神临` 是最简单的正则表达式——两个普通汉字。只要消息中**任意位置**包含“神临”，就匹配成功。

| 输入 | 是否匹配 | 原因 |
|------|---------|------|
| `神临` | ✅ | 完全包含 |
| `我神临了` | ✅ | 子串匹配 |
| `神来了` | ❌ | 不包含“神临” |

> **要点：** 引擎用 `search()` 匹配，默认搜索子串。如果要求整条消息完全等于某个模式，需要加 `^` 和 `$` 锚点。

### 4.2 锚点 + 捕获组——`like_reply` 规则

```toml
[[rules]]
name           = 'like_reply'
patterns       = ['^我喜欢(.+)$', '^喜欢(.+)$']
reply_template = '还在$1'
rate_limit_key = 'like_reply'
priority       = 60
```

**正则分析：**

```
^我喜欢(.+)$
│       │  │
│       │  └─ $ 锚定结尾
│       └──── (.+) 捕获组：一个或多个任意字符
└──────────── ^ 锚定开头
```

**关键概念——捕获组 `(...)`：**

圆括号将匹配到的内容“捕获”起来，存入编号组中：
- `$0` / `group(0)`：整个匹配结果
- `$1` / `group(1)`：第一个括号捕获的内容
- `$2` / `group(2)`：第二个括号捕获的内容……

```python
import re
m = re.search(r"^我喜欢(.+)$", "我喜欢打游戏")
print(m.group(0))  # “我喜欢打游戏”（整个匹配）
print(m.group(1))  # “打游戏”（第一个捕获组）
```

回复模板 `还在$1` 中的 `$1` 会被替换为捕获组 1 的内容，最终回复变成 `还在打游戏`。

| 输入 | 匹配？ | `$1` 的值 | 回复 |
|------|--------|----------|------|
| `我喜欢打游戏` | ✅ | `打游戏` | `还在打游戏` |
| `喜欢摸鱼` | ✅ | `摸鱼` | `还在摸鱼` |
| `我很喜欢你` | ❌ | — | 不匹配（因为“我”后面不是“喜欢”） |

### 4.3 非贪婪匹配 + 命名捕获组——`play_target` 规则

```toml
[[rules]]
name           = 'play_target'
patterns       = ['玩(?P<target>.+?)玩的']
reply_template = '{target}怎么你了'
rate_limit_key = 'play_target'
priority       = 85
```

**正则分析：**

```
玩(?P<target>.+?)玩的
│  │              │
│  │              └─ 非贪婪量词 +?
│  └────────────── (?P<target>...) 命名捕获组
└──────────────── 字面字符“玩”
```

**关键概念——命名捕获组 `(?P<name>...)`：**

普通捕获组用数字编号（`$1`、`$2`），命名捕获组则赋予一个有意义的名字：

```python
import re
m = re.search(r"玩(?P<target>.+?)玩的", "玩原神玩的")
print(m.group("target"))     # "原神"
print(m.groupdict())         # {"target": "原神"}
```

在模板中可以直接用 `{target}` 引用，可读性更好。

**关键概念——非贪婪 `.+?`：**

如果使用贪婪的 `.+`，面对 `玩王者玩原神玩的` 这种输入：
- `.+`（贪婪）→ 捕获 `王者玩原神`
- `.+?`（非贪婪）→ 捕获 `王者`（遇到第一个“玩的”就停止）

### 4.4 反向引用——`double_char_ni_de` 规则

```toml
[[rules]]
name           = 'double_char_ni_de'
patterns       = ['^([\u4e00-\u9fa5])(\1)你的$']
reply_template = '$1牛魔'
rate_limit_key = 'double_char_ni_de'
priority       = 80
```

**正则分析：**

```
^([\u4e00-\u9fa5])(\1)你的$
│ │               ││
│ │               │└─ \1 反向引用：必须与第 1 组相同
│ │               └── ( ) 第 2 个捕获组
│ └─────────────── [\u4e00-\u9fa5] 任意汉字（第 1 个捕获组）
└──────────────── ^ 锚定开头
```

**关键概念——反向引用 `\1`：**

`\1` 不是“再匹配一个汉字”，而是“匹配与第 1 个捕获组**完全相同**的内容”。这保证了两个字必须一模一样。

```python
import re
# ✅ 匹配：两个“牛”是相同的
re.search(r"^([\u4e00-\u9fa5])(\1)你的$", "牛牛你的")

# ❌ 不匹配：“牛”和“马”不同
re.search(r"^([\u4e00-\u9fa5])(\1)你的$", "牛马你的")
```

| 输入 | 匹配？ | `$1` | 回复 |
|------|--------|------|------|
| `牛牛你的` | ✅ | `牛` | `牛牛魔` |
| `哈哈你的` | ✅ | `哈` | `哈牛魔` |
| `牛马你的` | ❌ | — | — |
| `abc你的` | ❌ | — | 非汉字不匹配 |

### 4.5 字符范围 + 量词——`sandwich_de` 规则

```toml
[[rules]]
name           = 'sandwich_de'
patterns       = ['^([\u4e00-\u9fa5])(.{2,})\1的$']
reply_template = '$2怎么你了！'
rate_limit_key = 'sandwich_de'
priority       = 75
```

**正则分析：**

```
^([\u4e00-\u9fa5])(.{2,})\1的$
│ │                │      │
│ │                │      └─ \1 反向引用：与开头汉字相同
│ │                └──── .{2,} 至少 2 个任意字符（第 2 组）
│ └──────────────── 任意汉字（第 1 组）
└────────────────── ^ 锚定开头
```

这个“三明治”结构要求：
1. 开头一个汉字 A
2. 中间至少两个字符 B（被捕获为 `$2`）
3. 再出现相同的汉字 A
4. 以“的”结尾

```python
import re
m = re.search(r"^([\u4e00-\u9fa5])(.{2,})\1的$", "冰红茶冰的")
print(m.group(1))  # "冰"
print(m.group(2))  # "红茶"
# 回复：“红茶怎么你了！”
```

| 输入 | 匹配？ | `$1` | `$2` | 回复 |
|------|--------|------|------|------|
| `冰红茶冰的` | ✅ | `冰` | `红茶` | `红茶怎么你了！` |
| `鸡你太美鸡的` | ✅ | `鸡` | `你太美` | `你太美怎么你了！` |
| `冰茶冰的` | ❌ | — | — | 中间只有 1 个字，不满足 `{2,}` |

### 4.6 多捕获组协同——`ntk_gongxi` 规则

```toml
[[rules]]
name           = 'ntk_gongxi'
patterns       = ['恭喜(?P<person>.+?)可以(称帝|撑地)了']
reply_template = '恭喜{person}可以$2了'
rate_limit_key = 'new_three_kingdoms'
priority       = 87
```

**正则分析：** 这条新三国规则展示了三种捕获方式的协同——命名捕获组 `(?P<person>...)` 提取人名，字符类选择 `(称帝|撑地)` 是一个普通捕获组（第 2 组），模板里 `{person}` 与 `$2` 混用，各自引用。

```
恭喜(?P<person>.+?)可以(称帝|撑地)了
│    │                │
│    │                └─ (A|B) 分支结构，同时是第 2 个捕获组
│    └──────────────── (?P<person>...) 命名捕获组
└───────────────────── 字面文字“恭喜”
```

| 输入 | `{person}` | `$2` | 回复 |
|------|-----------|------|------|
| `恭喜曹丕可以称帝了` | `曹丕` | `称帝` | `恭喜曹丕可以称帝了` |
| `恭喜刘禅可以撑地了` | `刘禅` | `撑地` | `恭喜刘禅可以撑地了` |
| `恭喜曹丕登基了` | — | — | 不匹配（缺“可以”和分支词） |

> **历史教学案例（非仓库规则）：** 曾有规则使用 `(?:的)?` 这样的**非捕获组 + 可选**结构——只分组不占用捕获组编号，在多捕获组规则里避免打乱 `$1`、`$2` 的编号。需要该技巧时可参考本节把 `(称帝|撑地)` 换成 `(?:称帝|撑地)` 对比理解：前者可用 `$2` 引用，后者不占编号。

### 4.7 命名捕获组 + 黑名单过滤——`i_do` 规则

```toml
[[rules]]
name           = 'i_do'
patterns       = ['^我(?P<verb>[\u4e00-\u9fa5]{2})[！!。，,？?]*$']
reply_template = '不准$1'
rate_limit_key = 'group_meme'
priority       = 20

[rules.blocked_named_groups]
verb = [
    '不会', '不能', '不要', '以为', '支持', '反对', '同意', '喜欢', '回去', '回家',
    '害怕', '希望', '忘了', '忘记', '担心', '明白', '来了', '知道', '觉得', '认为',
    '记得', '认识', '说过', '谢谢', '输了', '赢了',
]
```

**正则分析：**

```
^我(?P<verb>[\u4e00-\u9fa5]{2})[！!。，,？?]*$
│   │                          │              │
│   │                          │              └─ $ 结尾
│   │                          └── 零个或多个中英文标点
│   └──── (?P<verb>...) 命名捕获组，名为 verb
└──── ^ 开头 + 字面“我”
```

这条规则的巧妙之处在于它结合了**正则匹配**和**程序逻辑过滤**：

1. 正则部分：匹配“我” + 两个汉字 + 可选标点
2. 程序部分：`[rules.blocked_named_groups]` 声明捕获组 `verb` 的黑名单，引擎在 `is_rule_match_allowed()`（`text_rules.py`）里检查命中的 `verb` 是否在列表中，命中则不触发、继续尝试下一条规则

| 输入 | 正则匹配？ | 黑名单过滤 | 最终结果 | 回复 |
|------|-----------|-----------|---------|------|
| `我吃饭` | ✅ verb=`吃饭` | 不在黑名单 | ✅ | `不准吃饭` |
| `我睡觉！` | ✅ verb=`睡觉` | 不在黑名单 | ✅ | `不准睡觉` |
| `我喜欢` | ✅ verb=`喜欢` | **在黑名单** | ❌ | 不回复 |
| `我觉得` | ✅ verb=`觉得` | **在黑名单** | ❌ | 不回复 |
| `我ABC` | ❌ | — | ❌ | 非汉字不匹配 |

**模板中的 `$1`：** 虽然使用了命名捕获组 `(?P<verb>...)`，但 `$1` 仍然有效——命名捕获组同时拥有名称和数字编号。

按组号索引的黑名单（`blocked_groups`）用法相同，位置捕获组规则可用。

### 4.8 `fullmatch` + 接龙触发——`good_girl_chain`

**源码位置：** `src/quickquip/chat/good_girl_chain.py`（`GOOD_GIRL_START_PATTERN`）

```python
GOOD_GIRL_START_PATTERN = re.compile(r"^(.+?)是好(.+?)吗[？?]*$")
```

**正则分析：**

```
^(.+?)是好(.+?)吗[？?]*$
│ │        │     │     │
│ │        │     │     └─ $ 结尾
│ │        │     └── [？?]* 零个或多个问号
│ │        └──── 第 2 组：非贪婪匹配
│ └──────── 第 1 组：非贪婪匹配
└────────── ^ 开头
```

这条正则使用 `re.compile()` 预编译，然后通过 `.fullmatch()` 调用——要求**整条消息**完全匹配模式。

```python
# .fullmatch() = 隐含了 ^ 和 $（尽管这里已经写了）
start_match = GOOD_GIRL_START_PATTERN.fullmatch("小明是好学生吗？")
lead_char = start_match.group(1)[0]  # “小”（取第一个字）
```

| 输入 | 匹配？ | `group(1)` | `group(2)` |
|------|--------|-----------|-----------|
| `小明是好学生吗？` | ✅ | `小明` | `学生` |
| `猫猫是好猫猫吗` | ✅ | `猫猫` | `猫猫` |
| `是好人吗` | ❌ | — | 开头 `.+?` 至少需要一个字符 |
| `小明是好学生` | ❌ | — | 缺少“吗” |

命中后进入九步“好姐姐”接龙，接龙序列与捕获组引用语法见 §6.5。

### 4.9 中英文标点混用处理——`genshin_start` 规则

```toml
[[rules]]
name           = 'genshin_start'
patterns       = ['^(.+?)[，,]\s*启动[！!]*$']
reply_template = '该启动$1了，少爷'
rate_limit_key = 'group_meme'
priority       = 95
```

**正则分析：**

```
^(.+?)[，,]\s*启动[！!]*$
│ │    │   │       │    │
│ │    │   │       │    └─ $ 结尾
│ │    │   │       └── [！!]* 零个或多个中英文感叹号
│ │    │   └──── \s* 可选空白
│ │    └──────── [，,] 中文或英文逗号
│ └──────────── (.+?) 第 1 组：非贪婪
└────────────── ^ 开头
```

这条规则处理了中英文标点混用的情况——逗号可以是 `，` 或 `,`，感叹号可以是 `！` 或 `!`，逗号后还容忍空白。

| 输入 | 匹配？ | `$1` | 回复 |
|------|--------|------|------|
| `原神，启动！` | ✅ | `原神` | `该启动原神了，少爷` |
| `星铁,启动` | ✅ | `星铁` | `该启动星铁了，少爷` |
| `绝区零， 启动！！！` | ✅ | `绝区零` | `该启动绝区零了，少爷` |
| `启动！` | ❌ | — | 缺少逗号前的内容 |

---

## 5. 进阶特性详解

### 5.1 `re.sub` 与回调函数——模板引擎的秘密

QuickQuip 的回复模板中使用 `$1`、`$2` 作为占位符，而 Python 的 `str.format()` 使用 `{}`。项目通过 `re.sub()` 巧妙地桥接了两者。

**源码位置：** `src/quickquip/chat/text_rules.py`（`replace_regex_groups` 函数）

```python
def replace_regex_groups(template: str, match: re.Match) -> str:
    def repl(group_match: re.Match) -> str:
        group_index = int(group_match.group(1))
        try:
            return match.group(group_index) or ""
        except IndexError:
            return ""
    return re.sub(r"\$(\d+)", repl, template)
```

**工作流程：**

1. `re.sub(r"\$(\d+)", repl, template)` 在模板中搜索 `$数字` 模式
2. 每找到一个，就调用 `repl` 回调函数
3. 回调函数提取数字（如 `$1` 中的 `1`），从原始匹配中取出对应的捕获组值
4. 用该值替换模板中的 `$1`

```python
# 示例流程
template = "还在$1"
# re.sub 找到 $1 → 调用 repl → repl 从 match 中取 group(1) → 返回“打游戏”
# 最终结果：“还在打游戏”
```

**`re.sub` 回调的正则本身：**

```
\$(\d+)
│  │
│  └── (\d+) 捕获一个或多个数字
└──── \$ 转义的美元符号
```

### 5.2 `match.groupdict()` 与动态上下文

**源码位置：** `src/quickquip/chat/text_rules.py`（规则匹配主循环中的上下文合并）

```python
context = {**base_context, **match.groupdict()}
```

`match.groupdict()` 返回所有**命名捕获组**的字典。例如：

```python
import re
m = re.search(r"玩(?P<target>.+?)玩的", "玩原神玩的")
m.groupdict()  # {"target": "原神"}
```

项目将它与基础上下文合并，使得模板中既可以用 `{target}`（来自正则），也可以用 `{sender_name}`（来自程序）。基础上下文由 `build_rule_context()` 构造，包含三个程序侧变量：

```python
base_context = {"current_time": "2026-08-30 14:00", "user_id": "123456", "sender_name": "张三"}
regex_context = {"target": "原神"}
context = {**base_context, **regex_context}
# {"current_time": ..., "user_id": ..., "sender_name": "张三", "target": "原神"}
```

### 5.3 预编译与热重载——引擎的现行选择

现行引擎对**全部规则正则统一预编译**：`text_rules.py` 在模块加载时把 `TEXT_REPLY_RULES` 里每条规则的 `patterns` 编译进模块级列表 `_COMPILED_PATTERNS`，匹配主循环只调用 `compiled.search(text)`：

```python
_COMPILED_PATTERNS: list[list[re.Pattern[str]]] = []

def recompile_patterns() -> None:
    _COMPILED_PATTERNS[:] = [
        [re.compile(p) for p in rule["patterns"]]
        for rule in TEXT_REPLY_RULES
    ]
```

注意 `recompile_patterns()` 用切片赋值 `_COMPILED_PATTERNS[:] = ...` **原地重建**列表——持有该列表引用的调用方（匹配主循环）无需重新导入即可看到新规则，这是配置热重载能即时生效的关键（见 §6.6）。

引擎之外仍有少量固定模式直接预编译为模块常量，例如 `good_girl_chain.py` 的 `GOOD_GIRL_START_PATTERN`、`chain_game.py` 的 `_REF_RE`。

> **性能说明：** Python 的 `re` 模块内部有缓存机制（默认缓存最近 512 个模式），即使逐条内联 `re.search` 也不会有明显性能损失；统一预编译的意义更多在于**热重载时能整体换新**，而非单纯的匹配速度。

---

## 6. 现行规则体系：从一条正则到一条生效的规则

写对正则只是第一步。一条规则要真正上线，还要放进 `config/chat_rules.toml` 的完整结构里，经过限流、开关、上下文判定等一系列机制。本节是这套体系的速览，权威参考始终是 `config/chat_rules.toml.example` 的注释。

### 6.1 `[[rules]]` 字段速查

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | ✅ | 规则唯一名称，用于统计（`/stats`）和开关控制（`/disable` / `/enable`） |
| `patterns` | ✅ | 触发正则列表（TOML 字面量字符串，单引号避免反斜杠转义），任意一条命中即触发 |
| `reply_template` | ✅* | 回复模板（与 `reply_templates` 二选一） |
| `rate_limit_key` | ✅ | 限流桶名称（需在 `[rate_limit_rules]` 定义，或引用系统预定义桶） |
| `priority` | ✅ | 整数越大越优先；同一消息命中多条规则时只触发最高优先级那条 |
| `reply_templates` | | 加权随机回复列表（见 §6.3） |
| `blocked_named_groups` | | 命名捕获组黑名单（见 §4.7） |
| `blocked_groups` | | 位置捕获组黑名单，按组号索引，用法同上 |

模板可用变量：`{sender_name}`（昵称）、`{current_time}`（北京时间）、`{user_id}`（QQ 号）、`{命名捕获组名}`、`$1` `$2` …（位置捕获组）。

### 6.2 `[rate_limit_rules]` 限流桶

每条规则通过 `rate_limit_key` 挂在一个限流桶上，桶的格式：

```toml
[rate_limit_rules]
group_meme = {global_limit = 6, user_limit = 3}
image_gen  = {global_limit = 10, user_limit = 2, scope = "global", window = 60}
```

| 字段 | 含义 |
|------|------|
| `global_limit` | 窗口内该桶最多触发次数 |
| `user_limit` | 窗口内同一用户最多触发次数 |
| `scope` | 分桶作用域，默认 `group`（按群独立分桶，私聊退化到合并桶）；`global` 为全群合并，用于保护 LLM、搜索、爬虫等跨会话共享资源 |
| `window` | 滑动窗口秒数，默认 60，可做长冷却彩蛋桶 |

要点：多条规则可共用一个桶（命中任意一条都消耗同一配额）；时区、LLM、贴吧、复读、接龙等系统规则的桶已在 `src/quickquip/chat/config.py` 预定义，TOML 里只需定义文字规则专用桶。

### 6.3 `reply_templates` 加权随机回复

把 `reply_template` 换成 `reply_templates` 列表即可让回复带权重随机，引擎用 `random.choices` 按权重抽取（`select_reply_template`，`text_rules.py`）：

```toml
[[rules]]
name           = 'example_random'
patterns       = ['示例触发词']
rate_limit_key = 'group_meme'
priority       = 10

[[rules.reply_templates]]
template = '回复A'
weight   = 2

[[rules.reply_templates]]
template = '回复B'
weight   = 1
```

上例中“回复A”被抽中的概率是“回复B”的两倍；不写 `weight` 默认为 1。

### 6.4 `[[context_rules]]` 上下文规则

普通 `[[rules]]` 只看当前消息；`context_rules` 在 pattern 命中后**再做一步语境判定**，只有语境合适才触发——用于“好啊”“竟然”这类单看本句会乱触发的常见词。执行时机在普通 rules 全部未命中之后、时区回复之前，仅群聊生效。

两种类型：

- `regex_context`：`context_conditions` 是上下文条件正则列表，需要在最近 `context_window` 条消息（默认 5）里搜到任意一条匹配才放行。**留空视为不放行**（该规则永不触发，模块加载时会打 warning）。
- `llm_context`：`llm_judge_prompt` 让 LLM 结合最近群聊记录判断语境，只输出 `{"trigger": true/false}` JSON；`llm_timeout`（默认 2.0s，超时视为不触发）与 `llm_cache_ttl`（按规则+群+文本缓存判定结果，默认 60s）控制成本。

字段细节与示例见 `config/chat_rules.toml.example` 的 `[[context_rules]]` 段（新三国梗里有 7 条实战配置可参考）。

### 6.5 `[[chain_games]]` 接龙游戏

接龙用一条 `trigger_pattern` 触发，然后按 `chain` 序列逐句推进：

- `chain[0]` 是 bot 的开场回复；奇数位（`chain[1]`、`chain[3]`…）是用户要说的内容；偶数位（`chain[2]`、`chain[4]`…）是 bot 的回复
- **奇数长度**：最后一个 bot 回复发出后会话自动结束
- **偶数长度**：最后一个元素是“静默终止 token”，用户在任意时刻发出它，会话立即结束且 bot 不回复
- 每步超时 `timeout_seconds`（默认 60）

接龙序列可以引用触发正则的捕获组，语法由 `chain_game.py` 的 `_REF_RE = r"\$(\d+)(?:\[(-?\d+)\])?"` 支持：

| 写法 | 含义 |
|------|------|
| `$1` | 第 1 个捕获组的完整文本 |
| `$1[0]` | 第 1 个捕获组的首字符 |
| `$1[-1]` | 第 1 个捕获组的尾字符 |
| `$1[2]` | 第 1 个捕获组中索引为 2 的字符 |

用户步还支持“或”语法：`'句号|。'` 表示说“句号”或“。”皆可（按 `|` 拆分后精确匹配其一）。

内置的好姐姐接龙（9 元素奇数长度）是完整示例：

```toml
[[chain_games]]
name            = 'good_girl_chain'
trigger_pattern = '^(.+?)是好(.+?)吗[？?]*$'
chain           = ['别', '逗', '你', '$1[0]', '姐', '笑', '了', '句号|。', '🤣']
timeout_seconds = 60
rate_limit_key  = 'good_girl_chain_entry'
```

触发后：bot 说“别”→ 用户说“逗”→ bot 说“你”→ 用户说主语首字（`$1[0]`，如“小明是好学生吗”的“小”）→ bot 说“姐”→ 用户说“笑”→ bot 说“了”→ 用户说“句号”或“。”→ bot 以 🤣 收尾，会话自动结束。自定义接龙示例见 `.example` 模板的 `launch_chain`。

### 6.6 热重载与规则开关

改完 `config/chat_rules.toml` 不需要重启进程：

```text
修改 toml 文件
      │
      ├── 群里执行 /reload_rules（或 /reload_personas 重载人格）
      └── Web Admin 在线编辑并保存规则文件
      │
      ▼
reload_chat_rules()          ← src/quickquip/chat/config.py，重新解析 TOML
      │
      ▼
recompile_patterns()         ← text_rules.py，_COMPILED_PATTERNS[:] 原地重建
      │
      ▼
新规则即刻生效（无需重启；持旧列表引用的匹配循环立刻看到新规则）
```

运行期还可以按群开关单条规则：`/disable <规则名>`、`/enable <规则名>`（持久化，重启不丢），`/rules` 查看当前开关状态。规则名即 TOML 里的 `name` 字段。

---

## 7. 项目中的正则表达式全景索引

**配置侧正则的权威清单是 `config/chat_rules.toml.example`**：共 32 条命名规则——25 条 `[[rules]]`（含 18 条新三国 `ntk_*`）+ 7 条 `[[context_rules]]`（新三国语境判定）。部署方私有规则不在公开仓库。本文不逐一复制该清单（避免双份维护漂移），只索引**引擎与代码侧**的正则：

| 位置 | 正则 | 用途 |
|------|------|------|
| `src/quickquip/chat/text_rules.py` | `\$(\d+)` | 模板中 `$数字` 占位符替换 |
| `src/quickquip/chat/good_girl_chain.py` | `^(.+?)是好(.+?)吗[？?]*$` | 好姐姐接龙触发（预编译 + fullmatch） |
| `src/quickquip/chat/chain_game.py` | `\$(\d+)(?:\[(-?\d+)\])?` | 接龙序列捕获组引用（`$1`、`$1[0]`、`$1[-1]`） |
| `src/quickquip/chat/context_rules.py` | （配置驱动） | `patterns` 首筛 + `context_conditions` 上下文条件，正则均在 TOML 中定义 |
| `src/quickquip/sts/config.py` | `^([一-鿿]{2,5})了$` | 杀戮尖塔“xxx了”被动公式的整句锚定（命中词表内名字则静默，详见 `sts-formula.md`） |

其余系统模块（时区猜测、复读检测、唤醒等）的正则分散在各自源码中，不属于 TOML 规则体系，以源码为准。

---

## 8. 常见陷阱与调试技巧

### 8.1 忘记使用原始字符串

```python
# 错误：\b 被 Python 解释为退格符
pattern = "我\b"

# 正确：r 前缀保留反斜杠
pattern = r"我\b"
```

TOML 侧同理：patterns 要用单引号字面量字符串（`'^我喜欢(.+)$'`）。双引号基本字符串里 `一` 会被 TOML 转义成实际汉字（碰巧还能用），而 `\1` 这类反向引用是 TOML 非法转义，会直接解析失败。

### 8.2 贪婪匹配导致的意外

```python
import re

# 贪婪：匹配到最后一个“玩的”
re.search(r"玩(.+)玩的", "玩A玩B玩的").group(1)
# 结果：“A玩B” —— 可能不是你想要的

# 非贪婪：匹配到第一个“玩的”
re.search(r"玩(.+?)玩的", "玩A玩B玩的").group(1)
# 结果：“A” —— 通常更符合预期
```

**经验法则：** 当捕获的内容“比预期多”时，检查是否应该使用非贪婪量词 `+?` 或 `*?`。

### 8.3 `search` vs `match` vs `fullmatch`

| 方法 | 行为 | 等价写法 |
|------|------|---------|
| `re.search(p, s)` | 在字符串**任意位置**找第一个匹配 | — |
| `re.match(p, s)` | 只从字符串**开头**匹配 | `re.search(r"^" + p, s)` |
| `re.fullmatch(p, s)` | 要求**整个字符串**完全匹配 | `re.search(r"^" + p + r"$", s)` |

```python
import re

text = "我喜欢编程"

re.search(r"喜欢", text)     # 匹配成功（子串匹配）
re.match(r"喜欢", text)      # 不匹配（开头不是“喜欢”）
re.fullmatch(r"喜欢", text)  # 不匹配（整个字符串不等于“喜欢”）

re.match(r"我喜欢", text)      # 匹配成功（开头匹配）
re.fullmatch(r"我喜欢编程", text)  # 匹配成功（完全匹配）
```

QuickQuip 中的选择：
- TOML 规则统一走 `compiled.search()`，锚定由规则作者用 `^`、`$` 显式控制
- `good_girl_chain.py` 使用 `re.compile().fullmatch()`，是一种等价的风格选择

### 8.4 Unicode 汉字范围的局限

`[\u4e00-\u9fa5]` 覆盖了 CJK 统一汉字基本区（20,902 个字符），但不包括：
- 扩展区 A（`㐀-䶿`）
- 扩展区 B 及以后（需要代理对）
- 兼容汉字

对于群聊机器人来说，基本区已经覆盖了日常使用的绝大多数汉字，因此足够使用。STS 被动公式用的 `[一-鿿]` 是同一基本区的另一种写法。

### 8.5 调试正则的实用方法

**方法 1：Python 交互式环境**

```python
import re
pattern = r"^([\u4e00-\u9fa5])(\1)你的$"
test_cases = ["牛牛你的", "哈哈你的", "牛马你的", "AB你的"]
for tc in test_cases:
    m = re.search(pattern, tc)
    print(f"{tc:10s} -> {'MATCH' if m else 'NO MATCH'}", end="")
    if m:
        print(f"  groups={m.groups()}", end="")
    print()
```

**方法 2：在线工具**

- [regex101.com](https://regex101.com/)：支持可视化解析，选择 Python 风格
- [regexper.com](https://regexper.com/)：将正则表达式可视化为铁路图

**方法 3：使用 `re.VERBOSE` 模式编写带注释的正则**

```python
import re

pattern = re.compile(r"""
    ^                           # 开头
    (?P<verb>[\u4e00-\u9fa5]{2})  # 两个汉字，命名为 verb
    [！!。，,？?]*               # 可选的中英文标点
    $                           # 结尾
""", re.VERBOSE)
```

`re.VERBOSE` 模式忽略空白和 `#` 注释，让复杂正则更易读。（注意：TOML 规则的 patterns 不支持 VERBOSE——需要注释时写在 TOML 的 `#` 注释行里。）

**方法 4：真机验证**

规则是热重载的（§6.6）：把规则写进 `config/chat_rules.toml`，`/reload_rules` 后在测试群里直接发消息验证；`/stats` 能看到每条规则的触发次数，`/rules` 能确认开关状态。

---

## 9. 练习题

以下练习题基于 QuickQuip 的实际场景，难度逐步递增。

### 练习 1：基础匹配（难度 ★）

编写一个正则表达式，匹配消息中包含“yyds”（不区分大小写）的文本。

```python
# 提示：使用 re.IGNORECASE 标志
import re
pattern = r"yyds"
re.search(pattern, "这个真的是YYDS", re.IGNORECASE)
```

<details>
<summary>参考答案</summary>

```python
r"(?i)yyds"
# 或者
re.search(r"yyds", text, re.IGNORECASE)
```

`(?i)` 是内联标志，等价于 `re.IGNORECASE`。

</details>

### 练习 2：捕获组（难度 ★★）

编写正则匹配“XX太强了”格式的消息，捕获 XX 部分，用于回复“XX只是一般强”。

```python
# 输入：“张三太强了” → 捕获 "张三"
# 输入：“这个英雄太强了！” → 捕获 "这个英雄"
```

<details>
<summary>参考答案</summary>

```python
r"^(.+?)太强了[！!]*$"
```

使用非贪婪 `.+?` 防止过度匹配，末尾允许可选感叹号。

</details>

### 练习 3：叠词检测（难度 ★★★）

编写正则匹配任意汉字的三叠词（如“哈哈哈”“嘿嘿嘿”“呜呜呜”）。

```python
# 输入：“哈哈哈” → 匹配
# 输入：“哈哈” → 不匹配（只有两个）
# 输入：“哈呵哈” → 不匹配（不完全相同）
```

<details>
<summary>参考答案</summary>

```python
r"^([\u4e00-\u9fa5])\1\1$"
```

利用反向引用 `\1` 确保三个字符完全相同。

</details>

### 练习 4：新规则设计（难度 ★★★★）

为 QuickQuip 设计一条新的回复规则：当用户发送“XX比XX强”时，回复“那可不一定”。要求使用命名捕获组，并写成可直接放入 `chat_rules.toml` 的形式。

<details>
<summary>参考答案</summary>

```toml
[rate_limit_rules]
compare_reply = {global_limit = 6, user_limit = 3}

[[rules]]
name           = 'compare_reply'
patterns       = ['^(?P<a>.+?)比(?P<b>.+?)强$']
reply_template = '那可不一定'
rate_limit_key = 'compare_reply'
priority       = 40
```

别忘了限流桶要先在 `[rate_limit_rules]` 定义（或复用现成桶如 `group_meme`）。

> **注意：** 纯正则无法验证“两个捕获组内容不同”这一约束。如果需要这个逻辑，可以参考 `i_do` 规则的方式，在 `blocked_named_groups` 中做程序级过滤。

</details>

### 练习 5：理解执行流程（难度 ★★★★★）

阅读下面的代码（摘自现行 `src/quickquip/chat/text_rules.py`，略有精简），回答问题：

```python
def match_text_rule(text, user_id, sender_name, now=None):
    base_context = build_rule_context(user_id, sender_name, now=now)
    matched_rules = []
    for rule_index, rule in enumerate(TEXT_REPLY_RULES):
        for compiled in _COMPILED_PATTERNS[rule_index]:
            match = compiled.search(text)
            if not match:
                continue
            if not is_rule_match_allowed(rule, match):
                continue
            context = {**base_context, **match.groupdict()}
            template = select_reply_template(rule)
            matched_rules.append({
                "rule_name": rule["name"],
                "rate_limit_key": rule.get("rate_limit_key", rule["name"]),
                "reply": render_rule_reply(template, context, match),
                "priority": int(rule.get("priority", 0)),
                "rule_index": rule_index,
            })
            break
    matched_rules.sort(key=lambda item: (-item["priority"], item["rule_index"]))
    best_match = matched_rules[0]
    best_match.pop("rule_index", None)
    return best_match
```

**问题：** 如果一条消息同时命中了 `divine_arrival`（priority=100，配置文件中靠前）和 `ntk_nizoule`（priority=100，配置文件中靠后），最终会触发哪条规则？为什么？

<details>
<summary>参考答案</summary>

触发 `divine_arrival`。

排序键是 `(-priority, rule_index)`：priority 相同时，`rule_index` 小的排前——即**配置文件里写在前面的规则胜出**。`divine_arrival` 在 `.example` 模板里位于新三国规则段之前，`rule_index` 更小。

这也解释了为什么“拦截型”规则（想抢占某类消息的规则）要么写更高的 `priority`，要么写在配置文件更前面。

</details>

---

## 10. 延伸资源

### 官方文档

- [Python `re` 模块文档](https://docs.python.org/zh-cn/3/library/re.html)：最权威的参考
- [Python 正则表达式 HOWTO](https://docs.python.org/zh-cn/3/howto/regex.html)：官方入门教程

### 在线工具

- [regex101.com](https://regex101.com/)：交互式正则测试（推荐选择 Python 风格）
- [regexper.com](https://regexper.com/)：正则可视化铁路图
- [regexcrossword.com](https://regexcrossword.com/)：用填字游戏学正则

### 速查表

| 元字符 | 含义 | 示例 |
|--------|------|------|
| `.` | 任意字符（除换行） | `a.b` 匹配 `acb` |
| `^` | 字符串开头 | `^Hello` |
| `$` | 字符串结尾 | `world$` |
| `*` | 0 次或多次 | `ab*` 匹配 `a`、`ab`、`abb` |
| `+` | 1 次或多次 | `ab+` 匹配 `ab`、`abb` |
| `?` | 0 次或 1 次 | `ab?` 匹配 `a`、`ab` |
| `{n}` | 恰好 n 次 | `a{3}` 匹配 `aaa` |
| `{n,m}` | n 到 m 次 | `a{2,4}` 匹配 `aa`、`aaa`、`aaaa` |
| `[abc]` | 字符类 | `[aeiou]` 匹配元音 |
| `[^abc]` | 否定字符类 | `[^0-9]` 匹配非数字 |
| `\d` | 数字 `[0-9]` | |
| `\w` | 单词字符 `[a-zA-Z0-9_]` | |
| `\s` | 空白字符 | |
| `\b` | 单词边界 | |
| `(...)` | 捕获组 | |
| `(?:...)` | 非捕获组 | |
| `(?P<name>...)` | 命名捕获组 | |
| `\1` | 反向引用 | |
| `x|y` | 或 | `cat|dog` |

---

> **文档信息**
>
> - 本文档基于 QuickQuip 项目编写，代码示例均来自项目实际源码与 `config/chat_rules.toml.example`
> - 适用 Python 版本：≥ 3.11
> - 最后更新：2026-08-30
