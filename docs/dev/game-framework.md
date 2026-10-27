# 游戏框架开发者指南

本文面向已完成[开发环境搭建](../../CONTRIBUTING.md)、能阅读 Python 类和类型注解的贡献者，介绍如何将自己实现的游戏接入 QuickQuip 的消息管线、配置和金币系统。完整的 Session 型游戏可参考[数字炸弹](../../src/quickquip/games/number_bomb.py)，带金币结算的实例见 [21 点](../../src/quickquip/games/blackjack.py)。

---

## 目录结构

```
src/quickquip/games/
├── __init__.py           ← 统一 re-export
├── registry.py           ← GameRegistry / BaseGame / GameResult
├── scores.py             ← GameScores（JSON 持久化）
├── economy.py            ← GameEconomyStore（金币 / 签到 / 好感度）
├── config.py             ← 游戏参数加载（games.toml → games_config）
├── number_bomb.py        ← 数字炸弹（BaseGame 示例）
├── blackjack.py          ← 21 点（BaseGame + 金币）
├── russian_roulette.py   ← 俄罗斯轮盘（BaseGame + 金币）
└── niuniu/               ← 牛牛大作战（独立 RPG 系统，包）
    ├── __init__.py       ← 公共 API 重导出
    ├── cooldown.py       ← CooldownTracker（线程安全 CD）
    ├── store.py          ← NiuNiuStore（SQLite CRUD / 排行 / 运势）
    ├── events.py         ← 事件定义 + 消息模板 + get_comment()
    ├── gluing.py         ← 编排层（打胶消息 / CD / 写库，数值委托 dynamics）
    ├── fencing.py        ← 编排层（击剑消息 / CD / 写库，数值委托 dynamics）
    ├── dynamics.py       ← 数值算法纯函数 glue_resolve / fence_resolve_pvp / fence_resolve_bot
    └── text.py           ← NiuNiuText 数据类、TOML 加载器、内置文案预设
```

---

## 两种游戏模式

### Session 型游戏：BaseGame

适用于有明确开始和结束的一局游戏。继承 `BaseGame`，提供名称，并实现开始、结束、消息处理和活动状态查询；`aliases` 可按需覆盖。以下是接口骨架，省略了各方法的游戏逻辑：

```python
from quickquip.games.registry import BaseGame, GameResult
from typing import Optional

class MyGame(BaseGame):
    @property
    def name(self) -> str:
        return "我的游戏"

    @property
    def aliases(self) -> list[str]:
        return ["mygame", "mg"]  # /game start 的别名

    def start(self, group_id: str, user_id: str, start_arg: str = "") -> str:
        """开始游戏，返回开场消息。start_arg 来自 /game start 的附加参数。"""
        ...

    def stop(self, group_id: str) -> Optional[str]:
        """强制结束，返回结算消息或 None。"""
        ...

    def process(self, group_id: str, user_id: str, text: str, now_ts: float) -> Optional[GameResult]:
        """处理群消息。返回 GameResult 或 None（忽略）。"""
        ...

    def is_active(self, group_id: str) -> bool:
        """返回该群是否有进行中的 session。"""
        ...
```

在 `src/quickquip/app/message_pipeline.py` 中注册实例。若游戏构造函数接收金币依赖，可按以下片段注入：

```python
game_registry.register(MyGame(economy=game_economy))
```

消息处理返回 `GameResult`。注册表根据 `finished` 清理群与游戏的关联，并把回复、艾特、限流桶和统计规则交给消息管线。字段定义如下：

```python
from dataclasses import dataclass

@dataclass
class GameResult:
    reply: str                              # 回复文本
    at_user_id: Optional[str] = None        # 需要 @ 的用户
    finished: bool = False                  # True 时 GameRegistry 清理 session
    rate_limit_key: str = "game_interaction" # 限流 key
    rule_name: str = "game_interaction"     # 统计用规则名
```

每个游戏自己维护以 `group_id` 为键的会话状态，现有实现使用 `OrderedDict[str, Session]`。GameRegistry 管理“哪个群在玩哪个游戏”的映射。

### 持久 RPG 系统：独立 Store

适用于用户数据跨游戏 session 持久化的场景（如牛牛大作战）。不走 GameRegistry，直接在 `src/quickquip/app/message_pipeline.py` 中初始化单例，在 `src/quickquip/adapters/nonebot/commands.py` 或对应 `command_parts/` 中注册独立命令。

以下存储骨架展示连接管理；实际实现还需创建数据目录并定义 `_ensure_schema()`：

```python
from pathlib import Path
import sqlite3

class MyRPGStore:
    def __init__(self, path: str = "data/my_rpg.db"):
        self.path = Path(path)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn
```

---

## 配置系统

所有游戏参数集中在 `config/games.toml` 中。`src/quickquip/games/config.py` 提供配置 dataclass 和加载器。

### 配置 dataclass 层次

```
GameConfig
├── economy: EconomyConfig           ← sign_base_gold, streak_bonus, ...
├── number_bomb: NumberBombConfig    ← min/max_number, timeout_seconds
├── blackjack: BlackjackConfig       ← min_bet, max_players, ...
├── russian_roulette: RussianRouletteConfig ← cylinder_slots, ...
└── niuniu: NiuNiuConfig             ← fence_cooldown, decay_rate, ...
```

### 向新游戏添加可配置参数

1. 在 `config.py` 中新增 dataclass：

```python
from __future__ import annotations
from dataclasses import dataclass, field, fields
from typing import Any

@dataclass(slots=True)
class MyGameConfig:
    min_bet: int = 20
    timeout_seconds: int = 60

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> MyGameConfig:
        if not data:
            return cls()
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid and v is not None})
```

2. 在 `GameConfig` 中添加字段：
```python
my_game: MyGameConfig = field(default_factory=MyGameConfig)
```

3. 在 `load_games_config()` 中添加：
```python
my_game=MyGameConfig.from_dict(data.get("my_game")),
```

4. 游戏构造函数接收 config：
```python
def __init__(self, config: MyGameConfig | None = None):
    self._config = config or MyGameConfig()
```

5. 在 `src/quickquip/app/message_pipeline.py` 注入：
```python
game_registry.register(MyGame(config=games_config.my_game))
```

### `from_dict` 约定

- 只提取 dataclass 定义的字段名（通过 `fields()` 遍历），忽略 TOML 中的未知键
- `None` 值视为未设置，不覆盖默认值
- 缺失字段保留 `@dataclass` 声明的默认值

---

## GameEconomyStore API

金币系统对游戏开发者暴露以下接口：

下面的 API 签名摘要用于查找方法；实现见 `src/quickquip/games/economy.py`：

```text
class GameEconomyStore:
    # 账户查询
    def get_balance(self, user_id: str, group_id: str) -> dict
        # → {gold, affection, sign_streak, last_sign_date}

    # 金币操作
    def add_gold(self, user_id: str, group_id: str, amount: int) -> int
        # → 返回新余额
    def deduct_gold(self, user_id: str, group_id: str, amount: int) -> bool
        # → 余额不足返回 False

    # 原子转账（游戏结算用，严禁用于非游戏场景）
    def transfer_gold(self, from_user: str, to_user: str, group_id: str, amount: int) -> bool
        # → 余额不足自动回滚

    # 排行
    def get_rank(self, group_id: str, top_n: int = 10) -> list[dict]

    # 好感度
    def get_affection(self, user_id: str, group_id: str) -> int
    def add_affection(self, user_id: str, group_id: str, amount: int) -> int

    # 签到
    def sign_in(self, user_id: str, group_id: str, today: str = "") -> dict
```

账户查询与变更会自动创建缺失账户；排行读取群内已有账户。`transfer_gold` 使用 `BEGIN IMMEDIATE` 保证原子性，`deduct_gold` 通过 `WHERE gold >= ?` 检查余额。支持无金币模式的游戏在调用前检查 `self._economy is not None`。

---

## 添加新游戏的步骤

### Session 型游戏

1. 在 `src/quickquip/games/` 下创建 `my_game.py`
2. 继承 `BaseGame`，实现全部方法
3. 如需金币：构造函数接收 `economy: GameEconomyStore | None`
4. 在 `__init__.py` 中导出
5. 在 `src/quickquip/app/message_pipeline.py` 中注册
6. 在 `docs/user/group-games.md` 添加玩法说明

### RPG 系统

1. 在 `src/quickquip/games/` 下创建 store + 逻辑文件
2. 在 `src/quickquip/app/message_pipeline.py` 初始化单例
3. 在 `src/quickquip/adapters/nonebot/commands.py` 或对应 `command_parts/` 中注册独立命令
4. 在 `docs/user/group-games.md` 添加玩法说明

---

## 设计原则

1. **游戏数据按群隔离** — 金币账户按用户与群共同定位；BaseGame session 按 `group_id` 定位
2. **纯文本输出** — 游戏结果提供回复文本，由消息管线发送
3. **自带超时** — 所有交互式游戏必须有 `expires_at` 机制，防止僵尸 session
4. **金币 None-safe** — 所有 `self._economy` 调用前检查 `is not None`
5. **原子操作** — 多用户金币转账用 `transfer_gold` 在同一事务中完成
6. **单文件原则（session 型）** — session 型游戏一个 `.py` 文件，业务逻辑不跨文件拆分；RPG 系统可按域拆包（如 `niuniu/`）

---

## 超时模式

所有 session 型游戏遵循统一的超时模式：

```python
# 在 process() 开头检查
if now_ts > session.expires_at:
    return self._settle(key, session, "超时自动结算")

# 每次有效操作后刷新
session.expires_at = now_ts + TIMEOUT_SECONDS
```

各游戏在 `process()` 中检查超时并执行自己的结算，GameRegistry 根据返回的 `finished` 清理关联。超时时长由各游戏配置决定。

---

## CD 系统（NiuNiu 示例）

使用 `games/niuniu/cooldown.py` 的 `CooldownTracker`（`threading.Lock` 线程安全，查询时自动清理过期条目，重启重置）：

```python
from quickquip.games.niuniu.cooldown import CooldownTracker

_cd = CooldownTracker()

remaining = _cd.check(uid)  # 剩余 CD 秒数，0 表示就绪或已过期
_cd.set(uid, 300)           # 设置 300 秒 CD
_cd.clear(uid)              # 手动清除
```

牛牛各动作直接使用模块级单例 `glue_cd` / `fence_cd` / `fenced_cd` / `arrested_cd`。

---

## 命令注册约定

- Session 型游戏通过 `/game start`、`/game stop`、`/game score` 统一入口
- 游戏内消息（如“拿牌”、“开枪”）由 `GameRegistry.process()` 统一分发
- RPG 系统在 `src/quickquip/adapters/nonebot/commands.py` 或对应 `command_parts/` 中用 `on_command()` 独立注册
- 命令别名通过 `aliases=` 参数声明，如 `aliases={"签到"}`
