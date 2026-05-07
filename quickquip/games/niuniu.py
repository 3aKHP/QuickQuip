from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import random
import sqlite3
import time
from typing import Optional

from quickquip.games.config import NiuNiuConfig

# Module-level defaults — used when no config is provided.
# For deployed use, pass NiuNiuConfig to NiuNiuStore and read from store.config.
FENCE_COOLDOWN = 180
FENCED_PROTECTION = 300
GLUE_COOLDOWN = 180
UNSUBSCRIBE_GOLD = 500


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── in-memory cooldown state ────────────────────────────────────────────

_fence_cd: dict[str, float] = {}       # uid → next allowed fence time
_fenced_cd: dict[str, float] = {}      # uid → next allowed to-be-fenced time
_glue_cd: dict[str, float] = {}        # uid → next allowed glue time
_arrested_until: dict[str, float] = {} # uid → arrested until


def _check_cd(cd_map: dict[str, float], uid: str) -> float:
    """Return remaining CD seconds, or 0 if ready."""
    until = cd_map.get(uid, 0)
    remaining = until - time.time()
    return remaining if remaining > 0 else 0


def _set_cd(cd_map: dict[str, float], uid: str, seconds: float) -> None:
    cd_map[uid] = time.time() + seconds


# ── gluing events ───────────────────────────────────────────────────────

_GLUE_EVENTS = [
    {
        "name": "normal",
        "weight": 30,
        "category": "growth",
        "pos": [
            "你嘿咻嘿咻一下，促进了牛牛发育，牛牛增加了 {diff} cm！",
            "你打了个舒服痛快的🦶，牛牛增加了 {diff} cm！",
            "哇哦！你的一🦶让牛牛变长了 {diff} cm！",
            "你的牛牛感受到了你的热情，增加了 {diff} cm！",
        ],
        "neg": [
            "哦吼！？看来你的牛牛凹进去了 {diff} cm！",
            "你突发恶疾！你的牛牛凹进去了 {diff} cm！",
            "笑死，你因为打🦶过度导致牛牛凹进去了 {diff} cm！",
            "阿哦，你过度打🦶，牛牛缩短了 {diff} cm 呢！",
            "小打怡情，大打伤身，强打灰飞烟灭！牛牛缩短了 {diff} cm！",
        ],
        "zero": [
            "你打了个🦶，但是什么变化也没有，好奇怪捏~",
            "你的牛牛刚开始变长了，可过了一会又回来了，什么变化也没有",
            "你在打胶时，感觉这个世界似乎发生了什么变化",
        ],
    },
    {
        "name": "lucky_day",
        "weight": 5,
        "category": "growth",
        "pos": [
            "🍀 今天运势极佳！牛牛疯狂生长了 {diff} cm！",
            "幸运女神掀起了你的裙子！牛牛暴增 {diff} cm！",
            "黄历说今日宜打胶，果然！牛牛增长了 {diff} cm！",
        ],
    },
    {
        "name": "mirror",
        "weight": 5,
        "category": "mirror",
        "pos": [
            "🪞 你的牛牛穿过了镜子！长度反转了！现在 {new_length} cm！",
            "牛牛误入了异次元裂缝，正负颠倒！当前 {new_length} cm！",
            "镜之国度的魔法！你的牛牛变成了 {new_length} cm！",
        ],
    },
    {
        "name": "blessing",
        "weight": 3,
        "category": "jackpot",
        "pos": [
            "🌈 牛牛之神降下了祝福！牛牛暴涨 {diff} cm！！",
            "上古牛神显灵！你的牛牛获得了神力加持，暴增 {diff} cm！",
            "天降祥瑞！七彩祥云笼罩了你的牛牛，增长 {diff} cm！",
        ],
    },
    {
        "name": "gambler",
        "weight": 4,
        "category": "gambler",
        "pos": [
            "🎰 你押上了全部身家……赢了！牛牛暴涨 {diff} cm！！",
            "赌徒的胜利！牛牛狂增 {diff} cm！",
        ],
        "neg": [
            "🎰 你押上了全部身家……输光了！牛牛暴跌 {diff} cm...",
            "赌狗不得好死！牛牛缩水了 {diff} cm...",
        ],
    },
    {
        "name": "zen",
        "weight": 4,
        "category": "zen",
        "pos": [
            "🧘 你进入了贤者模式，牛牛宁静地生长了 {diff} cm",
            "心如止水，牛牛缓缓增长了 {diff} cm",
            "打坐冥想之后，牛牛平和地增加了 {diff} cm",
        ],
    },
    {
        "name": "frenzy",
        "weight": 4,
        "category": "frenzy",
        "pos": [
            "💥 你进入了狂暴状态！牛牛暴涨 {diff} cm！",
            "肾上腺素飙升！牛牛怒长了 {diff} cm！",
            "你磕了药一样疯狂打胶，牛牛暴增 {diff} cm！",
        ],
    },
    {
        "name": "nightmare",
        "weight": 3,
        "category": "shrinkage",
        "neg": [
            "👻 你做了一个关于牛牛的噩梦！吓缩了 {diff} cm...",
            "深夜惊醒，发现牛牛被鬼压床！缩短了 {diff} cm...",
        ],
    },
    {
        "name": "shrinkage",
        "weight": 8,
        "category": "shrinkage",
        "neg": [
            "由于你在换蛋期打胶，你的牛牛断掉了呢！当前长度 {new_length} cm！",
            "bro换蛋期就不要打胶了！你的牛牛萎缩了 {diff} cm！",
        ],
    },
    {
        "name": "arrested",
        "weight": 6,
        "category": "arrested",
        "pos": [
            "打胶时被窗外的路人发现了，对方报警了！你被抓走关进小黑屋 {ban_time}s！",
        ],
    },
    {
        "name": "special_boost",
        "weight": 4,
        "category": "growth",
        "pos": [
            "你收到了群主私发的女装，冲！！！牛牛长大了 {diff} cm！",
            "一股神秘力量涌来！牛牛暴增 {diff} cm！",
        ],
    },
]

# ── length comments ─────────────────────────────────────────────────────

_LENGTH_COMMENTS = {
    (-1000000000, -1000): [
        "你已经超越了维度的界限……深渊魅魔之神！",
        "凡人无法理解的凹度，你已经成为了传说！",
    ],
    (-1000, -100): [
        "哇哦！你已经进化成魅魔了！魅魔在击剑时有几率吞噬对方牛牛呢！",
    ],
    (-100, -50): [
        "嗯……好像已经穿过了身体吧……从另一面来看也可以算是凸出来的吧？",
        "WOW，真的凹进去了好多呢！",
    ],
    (-50, -25): [
        "这名女生，你的身体很健康哦！",
        "你已经是我们女孩子的一员啦！",
    ],
    (-25, -10): [
        "你已经是一名女生了呢！",
        "从女生的角度来说，你发育良好哦！",
        "你醒啦？你已经是一名女孩子啦！",
    ],
    (-10, 0): [
        "安了安了，不要伤心嘛，做女生有什么不好的啊",
        "加油加油！我看好你哦！",
        "成为香香软软的女孩子吧！",
    ],
    (0, 10): [
        "你行不行啊？细狗！",
        "虽然短，但是小小的也很可爱呢",
        "像一只蚕宝宝",
    ],
    (10, 25): [
        "唔……没话说",
        "已经很长了呢！",
    ],
    (25, 50): [
        "话说这种真的有可能吗？",
        "厚礼谢！",
        "已经突破天际了嘛……",
        "你马上要进化成牛头人了！！",
    ],
    (50, 100): [
        "你这个长度会死人的……！",
        "你是什么怪物，不要过来啊！！",
        "惊世骇俗！你已经进化成牛头人了！牛头人在击剑时有几率支配对手！",
    ],
    (100, 1000): [
        "你已经超越人类极限了……",
        "牛牛之王！",
    ],
    (1000, 1000000000): [
        "你已经是神话级别的存在了！牛牛突破了现实维度！",
        "凡人只能仰望你的长度……牛牛之神降临！",
    ],
}


def _comment(length: float) -> str:
    for (lo, hi), msgs in _LENGTH_COMMENTS.items():
        if lo < length <= hi:
            return random.choice(msgs)
    return "你的牛牛状态很特殊……"


# ── NiuNiuStore ─────────────────────────────────────────────────────────

class NiuNiuStore:
    """SQLite-backed persistent store for 牛牛大作战 user data."""

    def __init__(self, path: str = "data/niuniu.db", config: NiuNiuConfig | None = None):
        self.path = Path(path)
        self.config = config or NiuNiuConfig()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def connect(self) -> sqlite3.Connection:
        """Return a new SQLite connection with row_factory set."""
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    _connect = connect  # internal alias

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS niuniu_users (
                    uid        TEXT PRIMARY KEY,
                    length     REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS niuniu_records (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid           TEXT NOT NULL,
                    action        TEXT NOT NULL,
                    origin_length REAL NOT NULL,
                    new_length    REAL NOT NULL,
                    created_at    TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_records_uid
                ON niuniu_records(uid, id DESC);
                """
            )

    # ── user CRUD ───────────────────────────────────────────────────────

    def exists(self, uid: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM niuniu_users WHERE uid = ?", (uid,)
            ).fetchone()
            return row is not None

    def get_length(self, uid: str) -> Optional[float]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT length FROM niuniu_users WHERE uid = ?", (uid,)
            ).fetchone()
            return row["length"] if row else None

    def register(self, uid: str) -> float:
        """Create a new niuniu with random initial length. Returns the length."""
        length = _random_initial_length(self)
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO niuniu_users (uid, length, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (uid, length, now, now),
            )
        self._add_record(uid, "register", 0, length)
        return length

    def unsubscribe(self, uid: str) -> Optional[float]:
        """Delete niuniu. Returns old length or None if didn't exist."""
        old = self.get_length(uid)
        if old is None:
            return None
        with self._connect() as conn:
            conn.execute("DELETE FROM niuniu_users WHERE uid = ?", (uid,))
        self._add_record(uid, "unsubscribe", old, 0)
        return old

    def update_length(self, uid: str, new_length: float) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE niuniu_users SET length = ?, updated_at = ? WHERE uid = ?",
                (round(new_length, 2), now, uid),
            )

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM niuniu_users").fetchone()
            return row["c"] if row else 0

    # ── records ─────────────────────────────────────────────────────────

    def _add_record(self, uid: str, action: str, origin: float, new: float) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO niuniu_records (uid, action, origin_length, new_length, created_at) VALUES (?, ?, ?, ?, ?)",
                (uid, action, round(origin, 2), round(new, 2), _utc_now()),
            )

    def get_records(self, uid: str, limit: int = 10) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT action, origin_length, new_length, created_at FROM niuniu_records WHERE uid = ? ORDER BY id DESC LIMIT ?",
                (uid, limit),
            ).fetchall()
        return [
            {
                "action": r["action"],
                "origin_length": r["origin_length"],
                "new_length": r["new_length"],
                "diff": round(r["new_length"] - r["origin_length"], 2),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def latest_record_time(self, uid: str, action: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT created_at FROM niuniu_records WHERE uid = ? AND action = ? ORDER BY id DESC LIMIT 1",
                (uid, action),
            ).fetchone()
            return row["created_at"] if row else "暂无记录"

    # ── ranking ─────────────────────────────────────────────────────────

    def rank_by_length(self, limit: int = 10, user_ids: list[str] | None = None) -> list[dict]:
        """Rank by descending length (positive). Optionally filtered to *user_ids*."""
        with self._connect() as conn:
            if user_ids:
                placeholders = ",".join("?" for _ in user_ids)
                rows = conn.execute(
                    f"SELECT uid, length FROM niuniu_users WHERE length > 0 AND uid IN ({placeholders}) ORDER BY length DESC LIMIT ?",
                    [*user_ids, limit],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT uid, length FROM niuniu_users WHERE length > 0 ORDER BY length DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [{"uid": r["uid"], "length": r["length"]} for r in rows]

    def rank_by_depth(self, limit: int = 10, user_ids: list[str] | None = None) -> list[dict]:
        """Rank by ascending length (most negative = deepest)."""
        with self._connect() as conn:
            if user_ids:
                placeholders = ",".join("?" for _ in user_ids)
                rows = conn.execute(
                    f"SELECT uid, length FROM niuniu_users WHERE length < 0 AND uid IN ({placeholders}) ORDER BY length ASC LIMIT ?",
                    [*user_ids, limit],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT uid, length FROM niuniu_users WHERE length < 0 ORDER BY length ASC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [{"uid": r["uid"], "length": abs(r["length"])} for r in rows]

    def get_rank_position(self, uid: str) -> int:
        """Return the 1-based rank of *uid* among all users with positive length."""
        length = self.get_length(uid)
        if length is None or length <= 0:
            return -1
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM niuniu_users WHERE length > ?",
                (length,),
            ).fetchone()
            return (row["c"] if row else 0) + 1


# ── initial length ──────────────────────────────────────────────────────

def _random_initial_length(store: NiuNiuStore) -> float:
    """Match zhenxun's random initial length: 30th percentile × 0.9, or 10.0."""
    with store._connect() as conn:
        rows = conn.execute(
            "SELECT length FROM niuniu_users ORDER BY length ASC"
        ).fetchall()
    if not rows:
        return 10.0
    lengths = [r["length"] for r in rows]
    idx = min(int(len(lengths) * 0.3), len(lengths) - 1)
    return round(lengths[idx] * 0.9, 2)


# ── gluing (打胶) ───────────────────────────────────────────────────────

def gluing(store: NiuNiuStore, uid: str) -> tuple[str, float]:
    """Perform a gluing operation. Returns (result_message, new_length)."""
    origin = store.get_length(uid)
    if origin is None:
        return "你还没有牛牛呢！请先发送 注册牛牛", 0

    # Arrested check
    if _check_cd(_arrested_until, uid) > 0:
        remaining = int(_check_cd(_arrested_until, uid))
        return f"你还在小黑屋里！{remaining}s 后才能打胶", origin

    # Weighted event selection
    events = _GLUE_EVENTS
    names = [e["name"] for e in events]
    weights = [e["weight"] for e in events]
    chosen_name = random.choices(names, weights=weights, k=1)[0]
    event = next(e for e in events if e["name"] == chosen_name)

    cfg = store.config

    if event["category"] == "growth":
        coeff = {
            "lucky_day": cfg.glue_lucky_coefficient,
            "special_boost": cfg.glue_special_coefficient,
        }.get(event["name"], 1.0)
        diff = _glue_growth(origin, coeff, cfg.glue_growth_scale)
        new_length = round(origin + diff, 2)
        if diff > 0 and "pos" in event:
            msg = random.choice(event["pos"]).format(diff=abs(diff))
        elif diff < 0 and "neg" in event:
            msg = random.choice(event["neg"]).format(diff=abs(diff))
        else:
            msg = random.choice(event.get("zero", ["什么也没有发生…"])).format(diff=0)
    elif event["category"] == "shrinkage":
        effect = cfg.glue_nightmare_effect if event["name"] == "nightmare" else cfg.glue_shrinkage_effect
        if origin >= 0:
            new_length = round(origin * effect, 2)
        else:
            new_length = round(origin / effect, 2)
        diff = round(new_length - origin, 2)
        if "neg" in event:
            msg = random.choice(event["neg"]).format(diff=abs(diff), new_length=new_length)
        else:
            msg = f"你的牛牛萎缩了 {abs(diff)} cm！当前 {new_length} cm"
    elif event["category"] == "arrested":
        ban_time = cfg.glue_arrested_duration
        _set_cd(_arrested_until, uid, ban_time)
        new_length = origin
        diff = 0
        msg = random.choice(event.get("pos", ["你被抓走了！"])).format(ban_time=ban_time)
    elif event["category"] == "mirror":
        if abs(origin) < 0.01:
            new_length = origin
            msg = "你的牛牛太短了，镜子也找不到它……什么也没发生"
        else:
            new_length = round(-origin, 2)
            msg = random.choice(event["pos"]).format(new_length=new_length)
    elif event["category"] == "jackpot":
        diff = round(random.uniform(cfg.glue_blessing_min, cfg.glue_blessing_max), 2)
        new_length = round(origin + diff, 2)
        msg = random.choice(event["pos"]).format(diff=diff)
    elif event["category"] == "gambler":
        diff = round(random.uniform(cfg.glue_gambler_min, cfg.glue_gambler_max), 2)
        if random.random() < 0.5:
            new_length = round(origin + diff, 2)
            msg = random.choice(event["pos"]).format(diff=diff)
        else:
            diff = round(-diff, 2)
            new_length = round(origin + diff, 2)
            msg = random.choice(event["neg"]).format(diff=abs(diff))
    elif event["category"] == "zen":
        diff = round(random.uniform(cfg.glue_zen_min, cfg.glue_zen_max), 2)
        new_length = round(origin + diff, 2)
        msg = random.choice(event["pos"]).format(diff=diff)
    elif event["category"] == "frenzy":
        diff = round(random.uniform(cfg.glue_frenzy_min, cfg.glue_frenzy_max), 2)
        new_length = round(origin + diff, 2)
        msg = random.choice(event["pos"]).format(diff=diff)
    else:
        diff = _glue_growth(origin, 1.0, cfg.glue_growth_scale)
        new_length = round(origin + diff, 2)
        msg = f"你的牛牛变化了 {abs(diff)} cm"

    # Apply decay
    new_length = _apply_decay(new_length, store.config)
    store.update_length(uid, new_length)

    # Update CD
    _set_cd(_glue_cd, uid, store.config.glue_cooldown)

    store._add_record(uid, "gluing", origin, new_length)
    return msg, new_length


def _glue_growth(origin: float, coefficient: float = 1.0, scale: float = 200.0) -> float:
    """Calculate growth/shrinkage for gluing."""
    growth_factor = max(0.5, 1 - abs(origin) / scale)
    prob = random.choice([-0.6, -0.5, -0.4, -0.2, 0, 0.2, 0.4, 0.5, 0.6])
    if origin <= 0:
        diff = prob * 0.1 * abs(origin)
    else:
        diff = prob * 0.1 * origin
    return round(diff * growth_factor * coefficient, 2)


def _apply_decay(length: float, cfg: NiuNiuConfig) -> float:
    """Apply length decay using config values."""
    if length > 50:
        rate = cfg.decay_rate_high
    elif length < -50:
        rate = -cfg.decay_rate_high / 2
    else:
        rate = cfg.decay_rate_normal
    if length > 0:
        return max(0, length * (1 - rate))
    return max(cfg.decay_floor, length * (1 + rate * 0.8))


# ── fencing messages ────────────────────────────────────────────────────

_FENCE_WIN_POS = [
    "你以绝对的长度让对方屈服了！长度 +{gain} cm，对方 -{loss} cm！当前 {my_len} cm！",
    "一剑封喉！你将对手挑落马下！牛牛增长 {gain} cm，当前 {my_len} cm！",
    "击剑大胜利！你从对方身上夺取了 {gain} cm！当前 {my_len} cm！",
    "对方在你面前不堪一击！牛牛怒增 {gain} cm！",
    "你的牛牛坚不可摧！+{gain} cm，对手 -{loss} cm！",
]

_FENCE_WIN_NEG = [
    "哦吼！？你的牛牛在长大欸！凹进去的深度减少了 {gain} cm，当前 {my_len} cm！",
    "以凹制胜！凹牛牛反而膨胀了 {gain} cm！当前 {my_len} cm！",
    "负负得正！你的凹牛牛逆势增长 {gain} cm！",
]

_FENCE_LOSE_POS = [
    "对方以绝对的长度让你屈服了！长度 -{loss} cm，当前 {my_len} cm！",
    "技不如人！牛牛被对方折服，缩短了 {loss} cm...",
    "败北！你的牛牛缩水了 {loss} cm，当前 {my_len} cm...",
    "你被对手压倒了！牛牛减少了 {loss} cm！",
    "对手的牛牛比你想象的更硬！你损失了 {loss} cm...",
]

_FENCE_LOSE_NEG = [
    "哦吼！？你的牛牛因为击剑凹进去了！又凹了 {loss} cm！当前 {my_len} cm！",
    "雪上加霜！已经凹了还要继续凹...又陷进去 {loss} cm！",
    "反向击剑失败！牛牛凹得更深了 {loss} cm...",
]

# ── fencing events ──────────────────────────────────────────────────────

_FENCE_EVENTS = [
    {
        "name": "normal",
        "weight": 50,
    },
    {
        "name": "critical",
        "weight": 12,
        "win_pos": [
            "💥 暴击！你给予了对方致命一击！+{gain} cm，对方 -{loss} cm！",
            "这一剑贯穿天地！暴击！牛牛增长 {gain} cm！",
            "精准命中要害！暴击伤害！+{gain} cm！",
        ],
        "win_neg": [
            "💥 暴击！你的凹牛牛爆发了惊人力量！+{gain} cm！",
        ],
        "lose_pos": [
            "💥 对方使出了暴击！你遭受重创，-{loss} cm...",
            "天哪！对方打出了暴击！牛牛损失 {loss} cm...",
        ],
        "lose_neg": [
            "💥 暴击！你的牛牛被对方打得更凹了...",
        ],
    },
    {
        "name": "glancing",
        "weight": 12,
        "win_pos": [
            "双方擦肩而过，你略占上风！+{gain} cm",
            "这次击剑如同蜻蜓点水……你微微增长了 {gain} cm",
        ],
        "win_neg": [
            "轻轻一碰，你的凹牛牛稍微恢复了一点 +{gain} cm",
        ],
        "lose_pos": [
            "只是擦伤！你仅损失了 {loss} cm，不痛不痒",
            "有惊无险，仅仅缩水了 {loss} cm",
        ],
        "lose_neg": [
            "轻微碰撞，你的牛牛又凹了一点点...",
        ],
    },
    {
        "name": "reversal",
        "weight": 8,
        "win_pos": [
            "🔄 绝地翻盘！你以弱胜强，击溃了对手！+{gain} cm！",
            "惊天逆转！所有人都以为你会输……你赢了！+{gain} cm！",
            "逆天改命！你反杀了比你长的对手！+{gain} cm！",
        ],
        "win_neg": [
            "🔄 绝地翻盘！凹牛牛逆袭成功！+{gain} cm！",
        ],
        "lose_pos": [
            "🔄 你太大意了！被对手绝地翻盘！-{loss} cm...",
            "轻敌的代价！你被对手反杀，损失 {loss} cm...",
        ],
        "lose_neg": [
            "🔄 大意失荆州！被翻盘了...",
        ],
    },
    {
        "name": "dominate",
        "weight": 3,
        "win_pos": [
            "👹 牛头人威压降临！你支配了对手！+{gain} cm，对方 -{loss} cm！",
            "牛头人之力爆发！你将对手踩在脚下！+{gain} cm！！",
        ],
        "win_neg": [
            "👹 牛头人威压降临！你的凹牛牛顺势膨胀了 {gain} cm！",
        ],
        "lose_pos": [
            "👹 对方使出了牛头人威压！你被支配了，-{loss} cm...",
            "牛头人支配了你！损失 {loss} cm...",
        ],
        "lose_neg": [
            "👹 对方牛头人威压！你的牛牛被压得更凹了...",
        ],
    },
    {
        "name": "succubus_devour",
        "weight": 3,
        "win_pos": [
            "👁 魅魔吞噬！你从对方身上夺取了 {gain} cm，对方损失 {loss} cm！",
            "魅魔之吻吸走了对方的力量！你增长了 {gain} cm！",
        ],
        "win_neg": [
            "👁 魅魔吞噬！你的凹度吸收了对方 {gain} cm！",
        ],
        "lose_pos": [
            "👁 魅魔吞噬反噬！对方夺取了你 {loss} cm...",
            "你被魅魔吸走了 {loss} cm！",
        ],
        "lose_neg": [
            "👁 魅魔吞噬反噬！你被对方吸得更凹了...",
        ],
    },
    {
        "name": "slip",
        "weight": 8,
        "lose_pos": [
            "💨 你脚下一滑！没刺到对方反而伤了自己！-{loss} cm...",
            "手滑了！你的牛牛撞到了墙上，损失 {loss} cm...",
            "一个趔趄！你的击剑动作失误，自损 {loss} cm！",
        ],
        "lose_neg": [
            "💨 你滑倒了！凹牛牛陷得更深了...",
        ],
    },
    {
        "name": "draw",
        "weight": 5,
        "msg": [
            "🤝 双方牛牛旗鼓相当！两败俱伤，各损失 {loss} cm！当前 {my_len} cm",
            "互不相让，双双重伤！你的牛牛损失了 {loss} cm...",
            "势均力敌！双方牛牛都受到了 {loss} cm 的损伤！",
        ],
    },
]

# ── no-niuniu target events ─────────────────────────────────────────────

_NO_NIUNIU_EVENTS = [
    {
        "name": "reject",
        "weight": 55,
        "msg": [
            "对方还没有牛牛呢！不能击剑！",
            "你对着空气一阵乱刺……对方根本没有牛牛！",
            "击剑？对方连牛牛都没注册，你跟空气击呢？",
            "对方处于无敌状态（没有牛牛），你的击剑无效！",
        ],
    },
    {
        "name": "force_register",
        "weight": 25,
        "msg": [
            "对方被你突如其来的击剑吓到了，慌乱中牛牛长了出来！足足 {oppo_len} cm！",
            "你的剑气唤醒了对方体内的牛牛之力！对方长出了 {oppo_len} cm 的牛牛！",
            "你一剑劈开了对方的牛牛封印！一只 {oppo_len} cm 的牛牛诞生了！",
        ],
    },
    {
        "name": "self_hurt",
        "weight": 20,
        "msg": [
            "你对着空气猛刺一剑，失去平衡摔倒了！牛牛损失 {loss} cm...",
            "目标没有牛牛，你的剑刺空闪到了腰！牛牛缩短了 {loss} cm...",
            "你对着虚空疯狂输出，结果用力过猛，牛牛磨损了 {loss} cm！",
        ],
    },
]

# ── bot fencing messages ────────────────────────────────────────────────

_FENCE_BOT_WIN = [
    "🤖 你竟然战胜了机器人！牛牛增长了 {gain} cm！但机器人毫无波澜，它只是一段代码...",
    "🤖 你击败了机器人守卫！+{gain} cm！机器人默默重启中...",
    "🤖 血肉之躯战胜了钢铁！你的牛牛增长了 {gain} cm！",
]

_FENCE_BOT_LOSE = [
    "🤖 你被机器人无情碾压！牛牛损失了 {loss} cm...机器人的牛牛是机械制成的！",
    "🤖 挑战机器人失败！你损失了 {loss} cm！机械牛牛果然更硬？",
    "🤖 机器人使出了精准的机械击剑！你败了，-{loss} cm...",
    "🤖 你被机器人的钢铁牛牛击溃了！损失 {loss} cm...",
]

_FENCE_BOT_DRAW = [
    "🤖 你和机器人势均力敌！双方各损失 {loss} cm！当前 {my_len} cm",
    "🤖 机器人和你打成了平手！两败俱伤，你损失了 {loss} cm...",
]

# ── fencing (击剑) ─────────────────────────────────────────────────────

def _fence_no_target(store: NiuNiuStore, my_uid: str, my_len: float, oppo_uid: str) -> str:
    """Handle fencing when the target has no niuniu registered."""
    chosen = random.choices(_NO_NIUNIU_EVENTS, weights=[e["weight"] for e in _NO_NIUNIU_EVENTS], k=1)[0]

    if chosen["name"] == "reject":
        return random.choice(chosen["msg"])
    elif chosen["name"] == "force_register":
        oppo_len = store.register(oppo_uid)
        prefix = random.choice(chosen["msg"]).format(oppo_len=oppo_len)
        result = fencing(store, my_uid, oppo_uid)
        return prefix + "\n" + result
    elif chosen["name"] == "self_hurt":
        loss = round(random.uniform(store.config.fence_self_hurt_min, store.config.fence_self_hurt_max), 2)
        new_len = round(my_len - loss, 2)
        new_len = _apply_decay(new_len, store.config)
        store.update_length(my_uid, round(new_len, 2))
        store._add_record(my_uid, "fencing_self_hurt", my_len, new_len)
        _set_cd(_fence_cd, my_uid, store.config.fence_cooldown)
        return random.choice(chosen["msg"]).format(loss=loss)
    return "出了一点问题……"

def fencing(
    store: NiuNiuStore, my_uid: str, oppo_uid: str, *, oppo_is_bot: bool = False
) -> str:
    """Execute a fencing battle. Returns result message."""
    my_len = store.get_length(my_uid)
    if my_len is None:
        return "你还没有牛牛呢！请先发送 注册牛牛"

    oppo_len = store.get_length(oppo_uid)

    # Target has no niuniu — bot gets a phantom, others trigger events
    if oppo_len is None:
        if oppo_is_bot:
            oppo_len = round(random.uniform(store.config.fence_bot_phantom_min, store.config.fence_bot_phantom_max), 2)
        else:
            return _fence_no_target(store, my_uid, my_len, oppo_uid)

    origin_my = my_len
    origin_oppo = oppo_len

    # Win probability
    win_prob = _fence_win_prob(my_len, oppo_len)
    i_win = random.random() < win_prob

    # Select event
    chosen = random.choices(_FENCE_EVENTS, weights=[e["weight"] for e in _FENCE_EVENTS], k=1)[0]

    # Dominate eligibility: requires at least one 牛头人 (positive >= threshold)
    if chosen["name"] == "dominate":
        threshold = store.config.fence_devour_threshold
        if my_len < threshold and oppo_len < threshold:
            chosen = next(e for e in _FENCE_EVENTS if e["name"] == "normal")

    # Succubus devour eligibility: requires at least one 魅魔 (negative, abs >= threshold)
    if chosen["name"] == "succubus_devour":
        threshold = store.config.fence_devour_threshold
        qualifies = (
            (my_len < 0 and abs(my_len) >= threshold)
            or (oppo_len < 0 and abs(oppo_len) >= threshold)
        )
        if not qualifies:
            chosen = next(e for e in _FENCE_EVENTS if e["name"] == "normal")

    # Apply event effects on outcome
    if chosen["name"] == "reversal":
        i_win = not i_win
    elif chosen["name"] == "slip":
        i_win = False

    # Succubus devour — real steal mechanic, replaces normal damage
    if chosen["name"] == "succubus_devour":
        steal = round(min(abs(my_len), abs(oppo_len)) * store.config.fence_devour_steal_ratio, 2)
        loss_val = round(steal * 1.5, 2)
        if i_win:
            my_len = round(my_len + steal, 2)
            if not oppo_is_bot:
                oppo_len = round(oppo_len - loss_val, 2)
        else:
            my_len = round(my_len - loss_val, 2)
            if not oppo_is_bot:
                oppo_len = round(oppo_len + steal, 2)
        my_len = round(_apply_decay(my_len, store.config), 2)
        if not oppo_is_bot:
            oppo_len = round(_apply_decay(oppo_len, store.config), 2)
        store.update_length(my_uid, my_len)
        store._add_record(my_uid, "fencing", origin_my, my_len)
        if not oppo_is_bot:
            store.update_length(oppo_uid, oppo_len)
            store._add_record(oppo_uid, "fenced", origin_oppo, oppo_len)
            _set_cd(_fenced_cd, oppo_uid, store.config.fenced_protection)
        _set_cd(_fence_cd, my_uid, store.config.fence_cooldown)
        if oppo_is_bot:
            msgs = _FENCE_BOT_WIN if i_win else _FENCE_BOT_LOSE
        elif i_win:
            msgs = (chosen.get("win_neg") or _FENCE_WIN_NEG) if my_len < 0 else (chosen.get("win_pos") or _FENCE_WIN_POS)
        else:
            msgs = (chosen.get("lose_neg") or _FENCE_LOSE_NEG) if my_len < 0 else (chosen.get("lose_pos") or _FENCE_LOSE_POS)
        return random.choice(msgs).format(gain=steal, loss=loss_val, my_len=my_len)

    # Calculate change
    base_change = min(abs(my_len), abs(oppo_len)) * 0.1
    rd = abs(time.time() % 10 - 5) + random.uniform(0.13, 0.24) * base_change
    balance = max(0.3, 1 - abs(my_len - oppo_len) / 100)
    reduce_val = round(rd * 0.3 * balance, 2)

    # Draw — both lose a fixed small amount
    if chosen["name"] == "draw":
        reduce_val = round(random.uniform(store.config.fence_draw_min, store.config.fence_draw_max), 2)
        my_len = round(my_len - reduce_val, 2)
        my_len = round(_apply_decay(my_len, store.config), 2)
        store.update_length(my_uid, my_len)
        store._add_record(my_uid, "fencing_draw", origin_my, my_len)
        if not oppo_is_bot:
            oppo_len = round(oppo_len - reduce_val, 2)
            oppo_len = round(_apply_decay(oppo_len, store.config), 2)
            store.update_length(oppo_uid, oppo_len)
            store._add_record(oppo_uid, "fencing_draw", origin_oppo, oppo_len)
            _set_cd(_fenced_cd, oppo_uid, store.config.fenced_protection)
        _set_cd(_fence_cd, my_uid, store.config.fence_cooldown)
        msgs = _FENCE_BOT_DRAW if oppo_is_bot else chosen["msg"]
        return random.choice(msgs).format(loss=reduce_val, my_len=my_len)

    # Apply multiplier from config
    multiplier = {
        "critical": store.config.fence_critical_multiplier,
        "glancing": store.config.fence_glancing_multiplier,
        "dominate": store.config.fence_dominate_multiplier,
    }.get(chosen["name"], 1.0)
    reduce_val = round(reduce_val * multiplier, 2)

    if i_win:
        my_len = round(my_len + reduce_val, 2)
        if not oppo_is_bot:
            oppo_len = round(oppo_len - 0.8 * reduce_val, 2)
    else:
        my_len = round(my_len - reduce_val, 2)
        if not oppo_is_bot:
            oppo_len = round(oppo_len + 0.8 * reduce_val, 2)

    # Apply decay
    my_len = round(_apply_decay(my_len, store.config), 2)
    if not oppo_is_bot:
        oppo_len = round(_apply_decay(oppo_len, store.config), 2)

    loss_val = round(0.8 * reduce_val, 2)

    # Message: bot > event-specific > defaults
    if oppo_is_bot:
        msgs = _FENCE_BOT_WIN if i_win else _FENCE_BOT_LOSE
    elif i_win:
        if my_len < 0:
            msgs = chosen.get("win_neg") or _FENCE_WIN_NEG
        else:
            msgs = chosen.get("win_pos") or _FENCE_WIN_POS
    else:
        if my_len < 0:
            msgs = chosen.get("lose_neg") or _FENCE_LOSE_NEG
        else:
            msgs = chosen.get("lose_pos") or _FENCE_LOSE_POS
    msg = random.choice(msgs).format(gain=reduce_val, loss=loss_val, my_len=my_len)

    store.update_length(my_uid, my_len)
    store._add_record(my_uid, "fencing", origin_my, my_len)
    if not oppo_is_bot:
        store.update_length(oppo_uid, oppo_len)
        store._add_record(oppo_uid, "fenced", origin_oppo, oppo_len)
        _set_cd(_fenced_cd, oppo_uid, store.config.fenced_protection)

    _set_cd(_fence_cd, my_uid, store.config.fence_cooldown)

    return msg


def _fence_win_prob(a: float, b: float) -> float:
    """Probability that player A wins. abs(a) matters more than sign."""
    if abs(a) < 0.001 or abs(b) < 0.001:
        return 0.5
    p = 0.85
    ratio = max(abs(a), abs(b)) / min(abs(a), abs(b))
    reduction = p * 0.1 * (ratio - 1)
    p = p - reduction
    if a < 0:
        p = 1.0 - p
    return max(0.05, min(p, 0.85))
