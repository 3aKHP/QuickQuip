# 从零开始学习正则表达式 —— 以 QuickQuip 项目为例

> ⚠️ **过期提示（2026-08 发布前加注）**
>
> 本教程写于文字规则体系 **TOML 化之前**（最后更新 2026-03-16），其中与项目代码绑定的部分已过期：
>
> - **4.x 节与练习题中的规则配置示例是旧版 Python dict 语法**，现行规则配置为 TOML `[[rules]]` 格式，权威参考为 [`config/chat_rules.toml.example`](../../config/chat_rules.toml.example)（实际部署使用 `config/chat_rules.toml`）。
> - **文中所有行号引用均已失效**；凡写"`src/quickquip/chat/config.py` 第 N 行"处，请以 TOML 模板文件为准。
> - 部分示例规则（`kpl_final`、`master_protection`、`maggot_arrival`、`huaizhen_oversize`）是部署方私有规则，**已不在公开仓库**。
> - 优先级等具体数值以 `config/chat_rules.toml.example` 为准。
>
> **仍然有效的部分：** 正则语法本身、匹配思路（锚点/捕获组/反向引用/贪婪与非贪婪）与调试技巧不受配置格式变化影响，可放心学习。
>
> **现行参考点：**
>
> - 规则配置模板：`config/chat_rules.toml.example`
> - 规则匹配引擎：`src/quickquip/chat/text_rules.py`（预编译 `_COMPILED_PATTERNS` + `recompile_patterns()` 热重载）
> - 上下文规则：`src/quickquip/chat/context_rules.py`

> **面向读者：** 零基础的 Python 初学者，希望通过真实项目案例理解正则表达式。
>
> **前置要求：** 了解基本的 Python 语法（字符串、函数调用）。
>
> **源码指引：** 本文引用的源码路径以 `src/quickquip/` 下的主实现为准。`src/plugins/` 目录是 NoneBot2 插件入口层，只做 re-export，不包含业务逻辑。文字规则配置现为 `config/chat_rules.toml`（权威模板为 `config/chat_rules.toml.example`，由 `src/quickquip/chat/config.py` 加载），模板渲染实现位于 `src/quickquip/chat/text_rules.py`。

---

## 目录

1. [什么是正则表达式？](#1-什么是正则表达式)
2. [Python 中的正则表达式工具箱](#2-python-中的正则表达式工具箱)
3. [基础语法速查](#3-基础语法速查)
4. [从简单到复杂：逐步拆解项目实例](#4-从简单到复杂逐步拆解项目实例)
5. [进阶特性详解](#5-进阶特性详解)
6. [项目中的正则表达式全景索引](#6-项目中的正则表达式全景索引)
7. [常见陷阱与调试技巧](#7-常见陷阱与调试技巧)
8. [练习题](#8-练习题)
9. [延伸资源](#9-延伸资源)

---

## 1. 什么是正则表达式？

**正则表达式**（Regular Expression，简称 regex 或 regexp）是一种用来描述"文本模式"的微型语言。你可以把它想象成一个**超级升级版的搜索功能**：

- 普通搜索：在文本中找"猫" → 只能精确匹配"猫"这个字
- 正则搜索：在文本中找"任意一个汉字重复两次后跟`你的`" → 能匹配"牛牛你的""哈哈你的""嘿嘿你的"……

在 QuickQuip 项目中，正则表达式是**规则引擎的核心**。机器人收到一条群聊消息后，会依次用多个正则表达式去"试探"这条消息是否匹配某个趣味回复规则。一旦匹配成功，就提取关键信息、填入模板、发送回复。

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

Python 通过内置的 `re` 模块提供正则表达式支持。QuickQuip 项目中主要使用了以下两个函数：

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
r"神临"      # 匹配文本中出现的"神临"二字
r"四区"      # 匹配文本中出现的"四区"二字
r"怀真"      # 匹配文本中出现的"怀真"二字
```

QuickQuip 中大量"梗触发"使用的就是这种简单匹配（下例为 TOML 化前的旧 dict 写法；`master_protection` 为部署方私有示例，已不在公开仓库）：

```python
# 旧版 config.py 中的 divine_arrival 规则
{"patterns": [r"神临", r"降临"], ...}

# master_protection 规则（私有示例，已迁出公开仓库）
{"patterns": [r"四区", r"4区", r"四出", r"4出"], ...}
```

### 3.2 锚点——限定匹配位置

| 符号 | 含义 | 示例 |
|------|------|------|
| `^` | 字符串**开头** | `^我` 匹配以"我"开头的文本 |
| `$` | 字符串**结尾** | `的$` 匹配以"的"结尾的文本 |

当 `^` 和 `$` 同时出现时，要求**整个字符串**完全符合模式：

```python
r"^我喜欢(.+)$"    # 整条消息必须是"我喜欢..."的格式
r"^(.+?)玩的$"      # 不会匹配——但如果只需匹配子串，去掉 ^ 和 $
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
# double_char_ni_de 规则：匹配两个相同汉字 + "你的"
r"^([\u4e00-\u9fa5])(\1)你的$"

# i_do 规则：匹配"我" + 两个汉字
r"^我(?P<verb>[\u4e00-\u9fa5]{2})[！!。，,？?]*$"
```

### 3.4 量词——控制重复次数

| 量词 | 含义 | 示例 |
|------|------|------|
| `*` | 0 次或多次 | `[？?]*` 匹配零个或多个问号 |
| `+` | 1 次或多次 | `.+` 匹配至少一个任意字符 |
| `?` | 0 次或 1 次 | `(?:的)?` 可选的"的" |
| `{n}` | 恰好 n 次 | `[\u4e00-\u9fa5]{2}` 恰好两个汉字 |
| `{n,m}` | n 到 m 次 | `.{2,}` 至少两个字符 |

#### 贪婪 vs 非贪婪

默认情况下，量词是**贪婪**的——尽可能多地匹配：

```python
r"玩(.+)玩的"   # 贪婪：输入"玩A玩B玩的"会匹配到"A玩B"
r"玩(.+?)玩的"  # 非贪婪（加 ?）：匹配到"A"就停止
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
r"[？?]"       # 在字符类 [] 内，? 不需要转义
r"[！!。，,？?]*"  # 匹配零个或多个中英文标点
```

---
## 4. 从简单到复杂：逐步拆解项目实例

下面我们按照从简单到复杂的顺序，逐一拆解 QuickQuip 中每一条正则表达式的设计思路。

### 4.1 纯文字匹配——`divine_arrival` 规则

**规则出处：** 旧版 `src/quickquip/chat/config.py`（TOML 化前；现行规则见 `config/chat_rules.toml.example`）

```python
{
    "name": "divine_arrival",
    "patterns": [r"神临", r"降临"],
    "reply_template": "{current_time}，@{sender_name} 区从天降",
    "priority": 100,
}
```

**正则分析：**

```
神临
```

这是最简单的正则表达式——两个普通汉字。只要消息中**任意位置**包含"神临"，就匹配成功。

| 输入 | 是否匹配 | 原因 |
|------|---------|------|
| `神临` | ✅ | 完全包含 |
| `我神临了` | ✅ | 子串匹配 |
| `神来了` | ❌ | 不包含"神临" |

> **要点：** `re.search()` 默认搜索子串。如果要求整条消息完全等于某个模式，需要加 `^` 和 `$` 锚点。

### 4.2 锚点 + 捕获组——`like_reply` 规则

**规则出处：** 旧版 `src/quickquip/chat/config.py`（TOML 化前；现行规则见 `config/chat_rules.toml.example`）

```python
{
    "name": "like_reply",
    "patterns": [r"^我喜欢(.+)$", r"^喜欢(.+)$"],
    "reply_template": "还在$1",
    "priority": 60,
}
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

圆括号将匹配到的内容"捕获"起来，存入编号组中：
- `$0` / `group(0)`：整个匹配结果
- `$1` / `group(1)`：第一个括号捕获的内容
- `$2` / `group(2)`：第二个括号捕获的内容……

```python
import re
m = re.search(r"^我喜欢(.+)$", "我喜欢打游戏")
print(m.group(0))  # "我喜欢打游戏"（整个匹配）
print(m.group(1))  # "打游戏"（第一个捕获组）
```

回复模板 `还在$1` 中的 `$1` 会被替换为捕获组 1 的内容，最终回复变成 `还在打游戏`。

| 输入 | 匹配？ | `$1` 的值 | 回复 |
|------|--------|----------|------|
| `我喜欢打游戏` | ✅ | `打游戏` | `还在打游戏` |
| `喜欢摸鱼` | ✅ | `摸鱼` | `还在摸鱼` |
| `我很喜欢你` | ❌ | — | 不匹配（因为"我"后面不是"喜欢"） |

### 4.3 非贪婪匹配 + 命名捕获组——`play_target` 规则

**规则出处：** 旧版 `src/quickquip/chat/config.py`（TOML 化前；现行规则见 `config/chat_rules.toml.example`）

```python
{
    "name": "play_target",
    "patterns": [r"玩(?P<target>.+?)玩的"],
    "reply_template": "{target}怎么你了",
    "priority": 85,
}
```

**正则分析：**

```
玩(?P<target>.+?)玩的
│  │              │
│  │              └─ 非贪婪量词 +?
│  └────────────── (?P<target>...) 命名捕获组
└──────────────── 字面字符"玩"
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
- `.+?`（非贪婪）→ 捕获 `王者`（遇到第一个"玩的"就停止）

### 4.4 反向引用——`double_char_ni_de` 规则

**规则出处：** 旧版 `src/quickquip/chat/config.py`（TOML 化前；现行规则见 `config/chat_rules.toml.example`）

```python
{
    "name": "double_char_ni_de",
    "patterns": [r"^([\u4e00-\u9fa5])(\1)你的$"],
    "reply_template": "$1牛魔",
    "priority": 80,
}
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

`\1` 不是"再匹配一个汉字"，而是"匹配与第 1 个捕获组**完全相同**的内容"。这保证了两个字必须一模一样。

```python
import re
# ✅ 匹配：两个"牛"是相同的
re.search(r"^([\u4e00-\u9fa5])(\1)你的$", "牛牛你的")

# ❌ 不匹配："牛"和"马"不同
re.search(r"^([\u4e00-\u9fa5])(\1)你的$", "牛马你的")
```

| 输入 | 匹配？ | `$1` | 回复 |
|------|--------|------|------|
| `牛牛你的` | ✅ | `牛` | `牛牛魔` |
| `哈哈你的` | ✅ | `哈` | `哈牛魔` |
| `牛马你的` | ❌ | — | — |
| `abc你的` | ❌ | — | 非汉字不匹配 |

### 4.5 字符范围 + 量词——`sandwich_de` 规则

**规则出处：** 旧版 `src/quickquip/chat/config.py`（TOML 化前；现行规则见 `config/chat_rules.toml.example`）

```python
{
    "name": "sandwich_de",
    "patterns": [r"^([\u4e00-\u9fa5])(.{2,})\1的$"],
    "reply_template": "$2怎么你了！",
    "priority": 75,
}
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

这个"三明治"结构要求：
1. 开头一个汉字 A
2. 中间至少两个字符 B（被捕获为 `$2`）
3. 再出现相同的汉字 A
4. 以"的"结尾

```python
import re
m = re.search(r"^([\u4e00-\u9fa5])(.{2,})\1的$", "冰红茶冰的")
print(m.group(1))  # "冰"
print(m.group(2))  # "红茶"
# 回复："红茶怎么你了！"
```

| 输入 | 匹配？ | `$1` | `$2` | 回复 |
|------|--------|------|------|------|
| `冰红茶冰的` | ✅ | `冰` | `红茶` | `红茶怎么你了！` |
| `鸡你太美鸡的` | ✅ | `鸡` | `你太美` | `你太美怎么你了！` |
| `冰茶冰的` | ❌ | — | — | 中间只有 1 个字，不满足 `{2,}` |

### 4.6 可选分组 + 多捕获——`kpl_final` 规则

**规则出处：** 旧版 `src/quickquip/chat/config.py`（TOML 化前）。注：该规则为部署方私有示例，已不在公开仓库，此处仅作正则教学案例。

```python
{
    "name": "kpl_final",
    "patterns": [r"^(.+?)尽力[，,]\s*(.+?)犯罪[，,]\s*(.+?)(?:的)?(.{2})不团队$"],
    "reply_template": "我说$1才是最大的一条区有没有懂的",
    "priority": 200,
}
```

**正则分析：**

```
^(.+?)尽力[，,]\s*(.+?)犯罪[，,]\s*(.+?)(?:的)?(.{2})不团队$
 │         │   │  │          │   │  │    │       │
 │         │   │  │          │   │  │    │       └─ 恰好 2 个任意字符
 │         │   │  │          │   │  │    └───── (?:的)? 非捕获组+可选
 │         │   │  │          │   │  └────── 第 3 个捕获组
 │         │   │  │          │   └─── \s* 零个或多个空白
 │         │   │  │          └───── [，,] 中文或英文逗号
 │         │   │  └──────────── 第 2 个捕获组
 │         │   └──── [，,]\s* 逗号+可选空白
 │         └──────── 字面文字"尽力"
 └────────────────── 第 1 个捕获组（非贪婪）
```

**关键概念——非捕获组 `(?:...)`：**

普通的 `(...)` 会**捕获**内容并分配编号。如果你只想用括号进行**分组**但不需要捕获，就用 `(?:...)`：

```python
(?:的)?    # 可选的"的"字，但不占用捕获组编号
(的)?      # 也是可选的"的"字，但会占用一个捕获组编号
```

这在有多个捕获组时尤为重要——避免打乱 `$1`、`$2` 的编号。

**关键概念——字符类中的选择 `[，,]`：**

`[，,]` 匹配一个中文逗号 `，` 或英文逗号 `,`，确保两种输入习惯都能被识别。

**匹配示例：**

输入：`A尽力，B犯罪，C的坦克不团队`

| 捕获组 | 匹配内容 |
|--------|---------|
| `$1` | `A` |
| `$2` | `B` |
| `$3` | `C` |
| `$4` | `坦克` |

回复：`我说A才是最大的一条区有没有懂的`

### 4.7 命名捕获组 + 黑名单过滤——`i_do` 规则

**规则出处：** 旧版 `src/quickquip/chat/config.py`（TOML 化前；现行规则见 `config/chat_rules.toml.example`）

```python
{
    "name": "i_do",
    "patterns": [r"^我(?P<verb>[\u4e00-\u9fa5]{2})[！!。，,？?]*$"],
    "blocked_named_groups": {"verb": sorted(I_DO_BLOCKED_VERBS)},
    "reply_template": "不准$1",
    "priority": 20,
}
```

**正则分析：**

```
^我(?P<verb>[\u4e00-\u9fa5]{2})[！!。，,？?]*$
│   │                          │              │
│   │                          │              └─ $ 结尾
│   │                          └── 零个或多个中英文标点
│   └──── (?P<verb>...) 命名捕获组，名为 verb
└──── ^ 开头 + 字面"我"
```

这条规则的巧妙之处在于它结合了**正则匹配**和**程序逻辑过滤**：

1. 正则部分：匹配"我" + 两个汉字 + 可选标点
2. 程序部分：检查捕获到的 `verb` 是否在黑名单 `I_DO_BLOCKED_VERBS` 中

```python
# 黑名单中的动词不会触发回复
I_DO_BLOCKED_VERBS = {"不会", "不能", "不要", "喜欢", "知道", "觉得", ...}
```

| 输入 | 正则匹配？ | 黑名单过滤 | 最终结果 | 回复 |
|------|-----------|-----------|---------|------|
| `我吃饭` | ✅ verb=`吃饭` | 不在黑名单 | ✅ | `不准吃饭` |
| `我睡觉！` | ✅ verb=`睡觉` | 不在黑名单 | ✅ | `不准睡觉` |
| `我喜欢` | ✅ verb=`喜欢` | **在黑名单** | ❌ | 不回复 |
| `我觉得` | ✅ verb=`觉得` | **在黑名单** | ❌ | 不回复 |
| `我ABC` | ❌ | — | ❌ | 非汉字不匹配 |

**模板中的 `$1`：** 虽然使用了命名捕获组 `(?P<verb>...)`，但 `$1` 仍然有效——命名捕获组同时拥有名称和数字编号。

### 4.8 `fullmatch` + 接龙状态机——`good_girl_chain`

**源码位置：** 见 `src/quickquip/chat/good_girl_chain.py`（`GOOD_GIRL_START_PATTERN`）

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
lead_char = start_match.group(1)[0]  # "小"（取第一个字）
```

| 输入 | 匹配？ | `group(1)` | `group(2)` |
|------|--------|-----------|-----------|
| `小明是好学生吗？` | ✅ | `小明` | `学生` |
| `猫猫是好猫猫吗` | ✅ | `猫猫` | `猫猫` |
| `是好人吗` | ❌ | — | 开头 `.+?` 至少需要一个字符 |
| `小明是好学生` | ❌ | — | 缺少"吗" |

### 4.9 启动模式匹配——`genshin_start` 规则

**规则出处：** 旧版 `src/quickquip/chat/config.py`（TOML 化前；现行规则见 `config/chat_rules.toml.example`）

```python
{
    "name": "genshin_start",
    "patterns": [r"^(.+?)[，,]\s*启动[！!]*$"],
    "reply_template": "该启动$1了，少爷",
    "priority": 90,  # 注：旧版示例值，现行数值以 chat_rules.toml.example 为准
}
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

这条规则处理了中英文标点混用的情况——逗号可以是 `，` 或 `,`，感叹号可以是 `！` 或 `!`。

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

**源码位置：** 见 `src/quickquip/chat/text_rules.py`（`replace_regex_groups` 函数）

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
# re.sub 找到 $1 → 调用 repl → repl 从 match 中取 group(1) → 返回"打游戏"
# 最终结果："还在打游戏"
```

**`re.sub` 回调的正则本身：**

```
\$(\d+)
│  │
│  └── (\d+) 捕获一个或多个数字
└──── \$ 转义的美元符号
```

### 5.2 `match.groupdict()` 与动态上下文

**源码位置：** 见 `src/quickquip/chat/text_rules.py`（规则匹配主循环中的上下文合并）

```python
context = {**base_context, **match.groupdict()}
```

`match.groupdict()` 返回所有**命名捕获组**的字典。例如：

```python
import re
m = re.search(r"玩(?P<target>.+?)玩的", "玩原神玩的")
m.groupdict()  # {"target": "原神"}
```

项目将它与基础上下文合并，使得模板中既可以用 `{target}`（来自正则），也可以用 `{sender_name}`（来自程序）：

```python
base_context = {"sender_name": "张三", "current_time": "2026-03-16 14:00"}
regex_context = {"target": "原神"}
context = {**base_context, **regex_context}
# {"sender_name": "张三", "current_time": "2026-03-16 14:00", "target": "原神"}
```

### 5.3 `re.compile` vs 内联使用

项目中有两种使用正则的风格：

| 风格 | 示例 | 适用场景 |
|------|------|---------|
| **内联** | `re.search(pattern, text)` | 配置驱动，模式来自配置字典 |
| **预编译** | `PATTERN = re.compile(r"...")` | 固定模式，高频调用 |

`src/quickquip/chat/good_girl_chain.py` 中的接龙触发模式使用预编译：

```python
GOOD_GIRL_START_PATTERN = re.compile(r"^(.+?)是好(.+?)吗[？?]*$")
```

而 `src/quickquip/chat/text_rules.py` 中遍历配置列表时使用内联：

```python
for rule in TEXT_REPLY_RULES:
    for pattern in rule["patterns"]:
        match = re.search(pattern, text)  # 内联使用
```

> **注（已过期）：** 现行实现改为统一预编译——`text_rules.py` 启动时将全部规则 pattern 编译进 `_COMPILED_PATTERNS`，并通过 `recompile_patterns()` 支持热重载，不再逐条内联 `re.search`。上例仅为说明"内联 vs 预编译"两种风格。

> **性能说明：** Python 的 `re` 模块内部有缓存机制（默认缓存最近 512 个模式），所以对于少量模式，内联方式也不会有明显性能损失。

---

## 6. 项目中的正则表达式全景索引

下表列出了 QuickQuip 项目中所有正则表达式的位置、模式和用途：

### 6.1 文字彩蛋规则（旧版 `src/quickquip/chat/config.py` → `TEXT_REPLY_RULES`；现行配置见 `config/chat_rules.toml.example`）

> 注：`maggot_arrival`、`master_protection`、`huaizhen_oversize`、`kpl_final` 为部署方私有示例，已不在公开仓库，下表保留仅作正则教学参考。

| # | 规则名 | 正则表达式 | 用途 | 关键技术 |
|---|--------|-----------|------|---------|
| 1 | `divine_arrival` | `r"神临"`、`r"降临"` | 触发"区从天降"回复 | 纯文字匹配 |
| 2 | `play_target` | `r"玩(?P<target>.+?)玩的"` | 提取"玩XX玩的"中的内容 | 命名捕获组、非贪婪 |
| 3 | `double_char_ni_de` | `r"^([\u4e00-\u9fa5])(\1)你的$"` | 匹配叠字+"你的" | 反向引用、Unicode范围 |
| 4 | `sandwich_de` | `r"^([\u4e00-\u9fa5])(.{2,})\1的$"` | 匹配"三明治"结构 | 反向引用、量词范围 |
| 5 | `like_reply` | `r"^我喜欢(.+)$"`、`r"^喜欢(.+)$"` | 提取喜欢的内容 | 锚点、捕获组 |
| 6 | `maggot_arrival`（私有示例，已迁出） | `r"区临"`、`r"区来了"` | 触发"区从天降"变体 | 纯文字匹配 |
| 7 | `genshin_start` | `r"^(.+?)[，,]\s*启动[！!]*$"` | "XX，启动！"格式 | 字符类、可选量词 |
| 8 | `master_protection`（私有示例，已迁出） | `r"四区"`、`r"4区"`、`r"四出"`、`r"4出"` | 最高优先级保护 | 纯文字匹配 |
| 9 | `huaizhen_oversize`（私有示例，已迁出） | `r"怀真"`、`r"赵怀真"` | 触发固定回复 | 纯文字匹配 |
| 10 | `kpl_final`（私有示例，已迁出） | `r"^(.+?)尽力[，,]\s*(.+?)犯罪[，,]\s*(.+?)(?:的)?(.{2})不团队$"` | 复杂多捕获组 | 非捕获组、多组 |
| 11 | `i_do` | `r"^我(?P<verb>[\u4e00-\u9fa5]{2})[！!。，,？?]*$"` | "我XX"格式 | 命名捕获组、黑名单 |

### 6.2 接龙触发（`src/quickquip/chat/good_girl_chain.py`）

| 正则表达式 | 用途 | 关键技术 |
|-----------|------|---------|
| `r"^(.+?)是好(.+?)吗[？?]*$"` | 启动接龙会话 | 预编译、fullmatch |

### 6.3 模板引擎（`src/quickquip/chat/text_rules.py`）

| 正则表达式 | 用途 | 关键技术 |
|-----------|------|---------|
| `r"\$(\d+)"` | 在模板中查找 `$数字` 占位符 | 转义、回调替换 |

---

## 7. 常见陷阱与调试技巧

### 7.1 忘记使用原始字符串

```python
# 错误：\b 被 Python 解释为退格符
pattern = "我\b"

# 正确：r 前缀保留反斜杠
pattern = r"我\b"
```

### 7.2 贪婪匹配导致的意外

```python
import re

# 贪婪：匹配到最后一个"玩的"
re.search(r"玩(.+)玩的", "玩A玩B玩的").group(1)
# 结果："A玩B" —— 可能不是你想要的

# 非贪婪：匹配到第一个"玩的"
re.search(r"玩(.+?)玩的", "玩A玩B玩的").group(1)
# 结果："A" —— 通常更符合预期
```

**经验法则：** 当捕获的内容"比预期多"时，检查是否应该使用非贪婪量词 `+?` 或 `*?`。

### 7.3 `search` vs `match` vs `fullmatch`

| 方法 | 行为 | 等价写法 |
|------|------|---------|
| `re.search(p, s)` | 在字符串**任意位置**找第一个匹配 | — |
| `re.match(p, s)` | 只从字符串**开头**匹配 | `re.search(r"^" + p, s)` |
| `re.fullmatch(p, s)` | 要求**整个字符串**完全匹配 | `re.search(r"^" + p + r"$", s)` |

```python
import re

text = "我喜欢编程"

re.search(r"喜欢", text)     # 匹配成功（子串匹配）
re.match(r"喜欢", text)      # 不匹配（开头不是"喜欢"）
re.fullmatch(r"喜欢", text)  # 不匹配（整个字符串不等于"喜欢"）

re.match(r"我喜欢", text)      # 匹配成功（开头匹配）
re.fullmatch(r"我喜欢编程", text)  # 匹配成功（完全匹配）
```

QuickQuip 中的选择：
- 大多数规则使用 `re.search()`，因为规则配置中已经用 `^`、`$` 显式控制了锚定
- `good_girl_chain.py` 中使用 `re.compile().fullmatch()`，是一种等价的风格选择

### 7.4 Unicode 汉字范围的局限

`[\u4e00-\u9fa5]` 覆盖了 CJK 统一汉字基本区（20,902 个字符），但不包括：
- 扩展区 A（`\u3400-\u4dbf`）
- 扩展区 B 及以后（需要代理对）
- 兼容汉字

对于群聊机器人来说，基本区已经覆盖了日常使用的绝大多数汉字，因此足够使用。

### 7.5 调试正则的实用方法

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

`re.VERBOSE` 模式忽略空白和 `#` 注释，让复杂正则更易读。

---

## 8. 练习题

以下练习题基于 QuickQuip 的实际场景，难度逐步递增。

### 练习 1：基础匹配（难度 ★）

编写一个正则表达式，匹配消息中包含"yyds"（不区分大小写）的文本。

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

编写正则匹配"XX太强了"格式的消息，捕获 XX 部分，用于回复"XX只是一般强"。

```python
# 输入："张三太强了" → 捕获 "张三"
# 输入："这个英雄太强了！" → 捕获 "这个英雄"
```

<details>
<summary>参考答案</summary>

```python
r"^(.+?)太强了[！!]*$"
```

使用非贪婪 `.+?` 防止过度匹配，末尾允许可选感叹号。

</details>

### 练习 3：叠词检测（难度 ★★★）

编写正则匹配任意汉字的三叠词（如"哈哈哈""嘿嘿嘿""呜呜呜"）。

```python
# 输入："哈哈哈" → 匹配
# 输入："哈哈" → 不匹配（只有两个）
# 输入："哈呵哈" → 不匹配（不完全相同）
```

<details>
<summary>参考答案</summary>

```python
r"^([\u4e00-\u9fa5])\1\1$"
```

利用反向引用 `\1` 确保三个字符完全相同。

</details>

### 练习 4：新规则设计（难度 ★★★★）

为 QuickQuip 设计一条新的回复规则：当用户发送"XX比XX强"时，回复"那可不一定"。要求：
- 两个 XX 必须是不同的内容
- 使用命名捕获组

<details>
<summary>参考答案</summary>

```python
{
    "name": "compare_reply",
    "patterns": [r"^(?P<a>.+?)比(?P<b>.+?)强$"],
    "reply_template": "那可不一定",
    "rate_limit_key": "divine_arrival",
    "priority": 40,
}
```

> **注意：** 纯正则无法验证"两个捕获组内容不同"这一约束。如果需要这个逻辑，可以参考 `i_do` 规则的方式，在 `blocked_named_groups` 中做程序级过滤，或在 `is_rule_match_allowed` 中添加自定义逻辑。

</details>

### 练习 5：理解执行流程（难度 ★★★★★）

阅读下面的代码（来自 `src/quickquip/chat/text_rules.py`），回答问题：

```python
def match_text_rule(text, user_id, sender_name, now=None):
    base_context = build_rule_context(user_id, sender_name, now=now)
    matched_rules = []
    for rule_index, rule in enumerate(TEXT_REPLY_RULES):
        for pattern in rule["patterns"]:
            match = re.search(pattern, text)
            if not match:
                continue
            if not is_rule_match_allowed(rule, match):
                continue
            context = {**base_context, **match.groupdict()}
            matched_rules.append({...})
            break
    matched_rules.sort(key=lambda item: (-item["priority"], item["rule_index"]))
    return matched_rules[0] if matched_rules else None
```

**问题：** 如果一条消息同时匹配了 `divine_arrival`（priority=100）和 `master_protection`（priority=65536），最终会触发哪个规则？为什么？（注：`master_protection` 为部署方私有示例，已不在公开仓库；具体优先级数值以 `config/chat_rules.toml.example` 为准。）

<details>
<summary>参考答案</summary>

会触发 `master_protection`。

排序使用 `-item["priority"]`（取负数），所以 priority 越大越靠前。`65536 > 100`，因此 `master_protection` 排在 `divine_arrival` 之前，成为最终选中的规则。

这就是项目中曾使用 `PRIORITY_ABSOLUTE = 65_536` 的原因——确保某些规则永远优先。（注：该常量为旧版写法，现行 TOML 配置中直接为规则填写足够大的 priority 数值，以 `config/chat_rules.toml.example` 为准。）

</details>

---

## 9. 延伸资源

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
> - 本文档基于 QuickQuip 项目编写，所有代码示例均来自项目实际源码
> - 适用 Python 版本：≥ 3.11
> - 最后更新：2026-03-16
