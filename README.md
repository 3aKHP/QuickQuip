# QuickQuip — QQ 群聊妙语机器人 🤖💬

> 基于 [NoneBot2](https://nonebot.dev/) + [OneBot V11](https://github.com/nonebot/adapter-onebot) 的 QQ 群聊互动机器人，用妙语让群聊更有趣。

QuickQuip（双 Q 谐音 = QQ + Quip/妙语）是一个**轻量级、纯规则驱动**的 QQ 群聊机器人。它不依赖大模型，通过精心设计的正则匹配和状态机，在群聊中自动给出有趣的回复——猜测你的真实时区、跟读复读、玩文字梗、甚至和你接龙。

---

## ✨ 功能一览

### 🌍 时区作息猜测

当群友发送「早安」「晚安」等作息关键词时，机器人会根据当前北京时间反推全球最匹配的时区，幽默地"揭穿"你的真实所在地。

**触发词：** `起床` `早安` `醒了` `睡醒了` `起了` `苏醒` `晚安` `睡觉` `睡了` `睡啦` `困了` `眠了`

**回复示例：**
```
现在是北京时间2026-03-16 09:19，位于上海的@某某 要起床了。TA也有可能在东京或首尔。
```

### 🔁 复读检测

机器人会观察群内复读行为，并做出不同反应：

| 场景 | 行为 |
|------|------|
| **不同人**连续发送相同消息（第 2 条） | 跟读该消息 |
| **同一人**连续发送相同消息（第 2 条） | 复读但删掉最后一个字 |
| **同一人**连续刷屏（第 4 条） | @该用户 并发出警告 |

### 🎭 文字彩蛋规则

内置多条基于正则匹配的趣味回复规则，支持优先级排序：

| 规则名称 | 触发示例 | 回复示例 | 优先级 |
|---------|---------|---------|--------|
| `master_protection` | 四区 / 4区 | 你不许说他他是我跌 | `PRIORITY_ABSOLUTE` |
| `kpl_final` | A尽力，B犯罪，C的XX不团队 | 我说A才是最大的一条区有没有懂的 | 200 |
| `divine_arrival` | 神临 / 降临 | {时间}，@{昵称} 区从天降 | 100 |
| `maggot_arrival` | 区临 / 区来了 | {时间}，有自知之明的@{昵称} 区从天降 | 95 |
| `genshin_start` | 原神，启动！ | 该启动原神了，少爷 | 90 |
| `play_target` | 玩XX玩的 | XX怎么你了 | 85 |
| `double_char_ni_de` | 牛牛你的 | 牛牛魔 | 80 |
| `sandwich_de` | 冰红茶冰的 | 红茶怎么你了！ | 75 |
| `like_reply` | 我喜欢XX / 喜欢XX | 还在XX | 60 |
| `huaizhen_oversize` | 怀真 / 赵怀真 | 赵怀真还不超标啊 | 50 |
| `i_do` | 我XX（过滤常见口语） | 不准XX | 20 |

### 🔗 "好女孩"接龙

当有人发送 `XX是好XX吗？` 格式的消息时，机器人会启动接龙会话，逐字回复 `别 → 逗 → 你 → {首字} → 姐 → 笑 → 了 → 🤣`，群友可以参与接力完成整条链。会话有 60 秒超时保护。

**示例：**
```
用户：   小明是好学生吗？
机器人： 别
用户：   逗
机器人： 你
用户：   小
机器人： 姐
...
机器人： 🤣
```

### 🚦 频率限制

所有回复均受**滑动窗口限流**保护（默认 60 秒窗口），每条规则独立配置全局上限和单用户上限，防止刷屏：

| 规则 | 全局上限 | 单用户上限 |
|------|---------|-----------|
| 时区作息回复 | 3 次/分钟 | 1 次/分钟 |
| 彩蛋规则 | 6 次/分钟 | 3 次/分钟 |
| 复读跟读 | 8 次/分钟 | 3 次/分钟 |
| 接龙回复 | 20 次/分钟 | 10 次/分钟 |

---

## 📁 项目结构

```
QuickQuip/
├── bot.py                          # NoneBot2 入口，注册适配器并加载插件
├── .env                            # 环境变量配置（不纳入版本控制）
├── .gitignore                      # Git 忽略规则
├── test_tz.py                      # 全功能断言测试脚本
└── plugins/                        # 插件目录
    ├── tz_config.py                # 全局配置：关键词、时区映射、规则定义、限流参数
    ├── __init__.py                 # 包标记文件，便于测试和直接导入
    ├── tz_tracker.py               # 核心调度器：消息处理、回复分发、NoneBot 事件绑定
    ├── tz_utils.py                 # 时区工具函数：时差计算、地点格式化、候选时区查找
    ├── text_reply_rules.py         # 文字彩蛋规则引擎：正则匹配 + 模板渲染
    ├── repeat_detector.py          # 复读检测器：群维度状态跟踪
    ├── rate_limit.py               # 滑动窗口限流器：全局 + 用户双层限流
    └── good_girl_chain.py          # "好女孩"接龙状态机
```

---

## 🚀 快速开始

### 环境要求

- **Python** ≥ 3.11（使用了 `X | Y` 类型联合语法和 `zoneinfo` 模块）
- **NoneBot2** + **OneBot V11 适配器**
- OneBot V11 协议实现端（如 [Lagrange.OneBot](https://github.com/LagrangeDev/Lagrange.Core)、[NapCat](https://github.com/NapNeko/NapCatQQ) 等）

### 安装步骤

1. **克隆仓库**

   ```bash
   git clone https://github.com/3aKHP/QuickQuip.git QuickQuip
   cd QuickQuip
   ```

2. **创建虚拟环境并安装依赖**

   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # Linux / macOS
   source .venv/bin/activate

   pip install nonebot2 nonebot-adapter-onebot
   ```

3. **配置环境变量**

   在项目根目录创建 [`.env`](.env) 文件，参考 NoneBot2 文档配置连接参数：

   ```env
   DRIVER=~fastapi
   HOST=0.0.0.0
   PORT=8080
   ```

4. **启动机器人**

   ```bash
   python bot.py
   ```

### 运行测试

项目包含完整的断言测试，无需额外测试框架：

```bash
python test_tz.py
```

无输出即表示所有测试通过。脚本会打印部分回复示例供人工验证。

---

## ⚙️ 配置说明

所有配置集中在 [`plugins/tz_config.py`](plugins/tz_config.py) 中，可直接修改：

| 配置项 | 说明 | 默认值 |
|-------|------|--------|
| [`BEIJING_TIMEZONE`](plugins/tz_config.py:3) | 基准时区 | `Asia/Shanghai` |
| [`WAKE_TARGET`](plugins/tz_config.py:9) | 起床目标时间 | `07:30` |
| [`SLEEP_TARGET`](plugins/tz_config.py:10) | 睡觉目标时间 | `23:30` |
| [`WAKE_WORDS`](plugins/tz_config.py:6) | 起床触发词集合 | 起床、早安、醒了… |
| [`SLEEP_WORDS`](plugins/tz_config.py:7) | 睡觉触发词集合 | 晚安、睡觉、睡了… |
| [`RATE_LIMIT_WINDOW_SECONDS`](plugins/tz_config.py:12) | 限流滑动窗口大小 | `60` 秒 |
| [`RATE_LIMIT_RULES`](plugins/tz_config.py:13) | 各规则限流参数 | 见源码 |
| [`TEXT_REPLY_RULES`](plugins/tz_config.py:56) | 文字彩蛋规则列表 | 见源码 |

### 添加自定义回复规则

在 [`TEXT_REPLY_RULES`](plugins/tz_config.py:56) 列表中追加字典即可：

```python
{
    "name": "my_rule",                    # 规则唯一名称
    "patterns": [r"正则表达式"],            # 触发正则（支持多个）
    "reply_template": "回复模板",           # 支持 {sender_name}、{current_time}、$1 等
    "rate_limit_key": "my_rule",          # 限流 key（需在 RATE_LIMIT_RULES 中注册）
    "priority": 50,                       # 优先级（数字越大越优先）
}
```

**模板变量：**

| 变量 | 说明 |
|------|------|
| `{sender_name}` | 发送者昵称 |
| `{current_time}` | 当前北京时间（格式：`YYYY-MM-DD HH:MM`） |
| `{user_id}` | 发送者 QQ 号 |
| `$1`, `$2`, … | 正则捕获组 |
| `{命名捕获组}` | 正则命名捕获组（如 `(?P<target>...)` → `{target}`） |

---

## 🏗️ 架构设计

```
群消息
  │
  ▼
tz_tracker.resolve_reply()        ← 统一入口
  │
  ├─① repeat_detector             ← 复读检测（最高优先）
  │
  ├─② good_girl_chain             ← 接龙会话
  │
  ├─③ text_reply_rules            ← 彩蛋规则匹配
  │
  └─④ build_timezone_reply()      ← 时区作息猜测（兜底）
  │
  ▼
rate_limiter.allow()              ← 限流检查
  │
  ▼
发送回复 / 静默跳过
```

回复优先级从高到低：**复读 > 接龙 > 彩蛋规则 > 时区猜测**。其中部分近义彩蛋规则会故意共享同一个限流桶，避免短时间内连续刷屏。每条回复在发送前都经过限流器检查。

---

## 📄 许可证

本项目基于 [WTFPL](LICENSE) 发布 — **Do What The F\*ck You Want To**。想干嘛就干嘛。Copyright © 2026 [3aKHP](https://github.com/3aKHP)。

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！添加新的回复规则只需编辑 [`plugins/tz_config.py`](plugins/tz_config.py)，无需修改核心逻辑。
