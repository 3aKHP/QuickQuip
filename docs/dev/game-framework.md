# 游戏框架开发者指南

本文档介绍 QuickQuip 游戏系统的架构、扩展接口和开发约定。

---

## 目录结构

```
quickquip/games/
├── __init__.py           ← 统一 re-export
├── registry.py           ← GameRegistry / BaseGame / GameResult
├── scores.py             ← GameScores（JSON 持久化）
├── economy.py            ← GameEconomyStore（金币 / 签到 / 好感度）
├── number_bomb.py        ← 数字炸弹（BaseGame 示例）
├── blackjack.py          ← 21 点（BaseGame + 金币）
├── russian_roulette.py   ← 俄罗斯轮盘（BaseGame + 金币）
└── niuniu/               ← 牛牛大作战（独立 RPG 系统，包）
    ├── __init__.py       ← 公共 API 重导出
    ├── cooldown.py       ← CooldownTracker（线程安全 CD）
    ├── store.py          ← NiuNiuStore（SQLite CRUD / 排行 / 运势）
    ├── events.py         ← 事件定义 + 消息模板 + get_comment()
    ├── gluing.py         ← gluing() / _apply_decay()
    └── fencing.py        ← fencing() / _fence_win_prob() / 角色判定
```

---

## 两种游戏模式

### Session 型游戏：BaseGame

适用于有明确开始/结束的一局游戏。继承 `BaseGame`，实现 4 个方法：

```python
from quickquip.games.registry import BaseGame, GameResult

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

**注册**：在 `message_pipeline.py` 中注册并注入依赖：

```python
game_registry.register(MyGame(economy=game_economy))
```

**GameResult 字段**：

```python
@dataclass
class GameResult:
    reply: str                              # 回复文本
    at_user_id: Optional[str] = None        # 需要 @ 的用户
    finished: bool = False                  # True 时 GameRegistry 清理 session
    rate_limit_key: str = "game_interaction" # 限流 key
    rule_name: str = "game_interaction"     # 统计用规则名
```

**Session 管理**：每个游戏自己维护 `OrderedDict[str, Session]`，key 为 `group_id`。GameRegistry 只管理"哪个群在玩哪个游戏"的映射。

### 持久 RPG 系统：独立 Store

适用于用户数据跨游戏 session 持久化的场景（如牛牛大作战）。不走 GameRegistry，直接在 `message_pipeline.py` 中初始化单例，在 `commands.py` 中注册独立命令。

```python
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

所有游戏参数集中在 `config/games.toml` 中。`quickquip/games/config.py` 提供配置 dataclass 和加载器。

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
def __init__(self, config: MyGameConfig | None = None, ...):
    self._config = config or MyGameConfig()
```

5. 在 `message_pipeline.py` 注入：
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

```python
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

**要点**：
- 所有方法自动 `_ensure_account`，无需预先创建账户
- `transfer_gold` 使用 `BEGIN IMMEDIATE` 保证原子性
- `deduct_gold` 有余额检查（`WHERE gold >= ?`），不会出现负数
- 每个游戏调用方应自行处理 `if self._economy:` 的 None 检查（支持无金币模式）

---

## 添加新游戏的步骤

### Session 型游戏

1. 在 `quickquip/games/` 下创建 `my_game.py`
2. 继承 `BaseGame`，实现全部方法
3. 如需金币：构造函数接收 `economy: GameEconomyStore | None`
4. 在 `__init__.py` 中导出
5. 在 `message_pipeline.py` 中注册
6. 在 `docs/user/group-games.md` 添加玩法说明

### RPG 系统

1. 在 `quickquip/games/` 下创建 store + 逻辑文件
2. 在 `message_pipeline.py` 初始化单例
3. 在 `commands.py` 中注册独立命令
4. 在 `docs/user/group-games.md` 添加玩法说明

---

## 设计原则

1. **游戏数据按群隔离** — 金币账户、BaseGame session 的 key 都是 `group_id`
2. **纯文本输出** — 不使用 HTML/图片渲染，消息即时送达
3. **自带超时** — 所有交互式游戏必须有 `expires_at` 机制，防止僵尸 session
4. **金币 None-safe** — 所有 `self._economy` 调用前检查 `is not None`
5. **原子操作** — 多用户金币变动用 `transfer_gold`，不要手动 add + deduct
6. **单文件原则** — 每个游戏一个 `.py` 文件，业务逻辑不跨文件拆分

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

GameRegistry 不管理超时——各游戏自行在 `process()` 中检查。这样每个游戏可以有不同的超时时长。

---

## CD 系统（NiuNiu 示例）

使用模块级 dict + `time.time()` 的简单方案（重启重置）：

```python
_cd_map: dict[str, float] = {}

def _check_cd(cd_map, uid: str) -> float:
    remaining = cd_map.get(uid, 0) - time.time()
    return remaining if remaining > 0 else 0

def _set_cd(cd_map, uid: str, seconds: float):
    cd_map[uid] = time.time() + seconds
```

---

## 命令注册约定

- Session 型游戏通过 `/game start`、`/game stop`、`/game score` 统一入口
- 游戏内消息（如"拿牌"、"开枪"）由 `GameRegistry.process()` 统一分发
- RPG 系统在 `commands.py` 中用 `on_command()` 独立注册
- 命令别名用 `aliases=` 参数（如 `aliases={"签到"}`），不用重复注册
