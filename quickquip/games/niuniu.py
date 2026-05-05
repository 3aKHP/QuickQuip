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
QUICK_GLUE_WINDOW = 240
UNSUBSCRIBE_GOLD = 500


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── in-memory cooldown state ────────────────────────────────────────────

_fence_cd: dict[str, float] = {}       # uid → next allowed fence time
_fenced_cd: dict[str, float] = {}      # uid → next allowed to-be-fenced time
_glue_cd: dict[str, float] = {}        # uid → next allowed glue time
_glue_last: dict[str, float] = {}      # uid → last glue time (for rapid detection)
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
        "weight": 60,
        "category": "growth",
        "coefficient": 1.0,
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
        "rapid_pos": ["这么着急？牛牛只微微增长了 {diff} cm..."],
        "rapid_neg": ["bro你搞这么快只会适得其反！牛牛减少了 {diff} cm！"],
    },
    {
        "name": "shrinkage",
        "weight": 10,
        "category": "shrinkage",
        "effect": 0.5,
        "neg": [
            "由于你在换蛋期打胶，你的牛牛断掉了呢！当前长度 {new_length} cm！",
            "bro换蛋期就不要打胶了！你的牛牛萎缩了 {diff} cm！",
        ],
    },
    {
        "name": "arrested",
        "weight": 10,
        "category": "arrested",
        "ban_time": 180,
        "pos": [
            "打胶时被窗外的路人发现了，对方报警了！你被抓走关进小黑屋 {ban_time}s！",
        ],
    },
    {
        "name": "special_boost",
        "weight": 5,
        "category": "growth",
        "coefficient": 1.1,
        "pos": [
            "你收到了群主私发的女装，冲！！！牛牛长大了 {diff} cm！",
            "一股神秘力量涌来！牛牛暴增 {diff} cm！",
        ],
    },
    {
        "name": "rapid_penalty",
        "weight": 15,
        "category": "shrinkage",
        "effect": 0.9,
        "neg": [
            "这么着急？牛牛减少了 {diff} cm...",
            "bro你搞这么快只会适得其反！牛牛减少了 {diff} cm！",
        ],
    },
]

# ── length comments ─────────────────────────────────────────────────────

_LENGTH_COMMENTS = {
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
        "惊世骇俗！你已经进化成牛头人了！牛头人在击剑时有几率吞噬对方牛牛呢！",
    ],
    (100, 100000): [
        "你已经超越人类极限了……",
        "牛牛之王！",
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

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

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

    is_rapid = time.time() - _glue_last.get(uid, 0) < store.config.quick_glue_window

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

    if is_rapid and "rapid_neg" in event:
        # Use rapid variant for normal event
        diff = round(random.uniform(0.5, 1.5) * -1, 2)
        new_length = round(origin + diff, 2)
        msg = random.choice(event["rapid_neg"]).format(diff=abs(diff))
    elif event["category"] == "growth":
        diff = _glue_growth(origin, event.get("coefficient", 1.0))
        new_length = round(origin + diff, 2)
        if diff > 0 and "pos" in event:
            msg = random.choice(event["pos"]).format(diff=abs(diff))
        elif diff < 0 and "neg" in event:
            msg = random.choice(event["neg"]).format(diff=abs(diff))
        else:
            msg = random.choice(event.get("zero", ["什么也没有发生…"])).format(diff=0)
    elif event["category"] == "shrinkage":
        effect = event.get("effect", 0.5)
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
        ban_time = event.get("ban_time", 180)
        _set_cd(_arrested_until, uid, ban_time)
        new_length = origin
        diff = 0
        msg = random.choice(event.get("pos", ["你被抓走了！"])).format(ban_time=ban_time)
    else:
        diff = _glue_growth(origin, 1.0)
        new_length = round(origin + diff, 2)
        msg = f"你的牛牛变化了 {abs(diff)} cm"

    # Apply decay
    new_length = _apply_decay(new_length, store.config)
    store.update_length(uid, new_length)

    # Update CDs
    _set_cd(_glue_cd, uid, store.config.glue_cooldown)
    _glue_last[uid] = time.time()

    store._add_record(uid, "gluing", origin, new_length)
    return msg, new_length


def _glue_growth(origin: float, coefficient: float = 1.0) -> float:
    """Calculate growth/shrinkage for gluing."""
    growth_factor = max(0.5, 1 - abs(origin) / 200)
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


# ── fencing (击剑) ─────────────────────────────────────────────────────

def fencing(
    store: NiuNiuStore, my_uid: str, oppo_uid: str
) -> str:
    """Execute a fencing battle. Returns result message."""
    my_len = store.get_length(my_uid)
    oppo_len = store.get_length(oppo_uid)
    if my_len is None:
        return "你还没有牛牛呢！请先发送 注册牛牛"
    if oppo_len is None:
        return "对方还没有牛牛呢！不能击剑！"

    origin_my = my_len
    origin_oppo = oppo_len

    # Win probability
    win_prob = _fence_win_prob(my_len, oppo_len)
    i_win = random.random() < win_prob

    # Calculate change
    base_change = min(abs(my_len), abs(oppo_len)) * 0.1
    rd = abs(time.time() % 10 - 5) + random.uniform(0.13, 0.24) * base_change
    reduce_val = round(rd * 0.3, 2)
    balance = max(0.3, 1 - abs(my_len - oppo_len) / 100)
    reduce_val *= balance

    if i_win:
        my_len = round(my_len + reduce_val, 2)
        oppo_len = round(oppo_len - 0.8 * reduce_val, 2)
        if my_len < 0:
            msg = f"哦吼！？你的牛牛在长大欸！长大了 {abs(reduce_val)} cm！"
        else:
            msg = (
                f"你以绝对的长度让对方屈服了！你的长度增加 {reduce_val} cm，"
                f"对方减少了 {round(0.8 * reduce_val, 2)} cm！"
                f"你当前长度为 {my_len} cm！"
            )
    else:
        my_len = round(my_len - reduce_val, 2)
        oppo_len = round(oppo_len + 0.8 * reduce_val, 2)
        if my_len < 0:
            msg = (
                f"哦吼！？看来你的牛牛因为击剑而凹进去了！凹进去了 {reduce_val} cm！"
            )
        else:
            msg = (
                f"对方以绝对的长度让你屈服了！你的长度减少 {reduce_val} cm，"
                f"当前长度 {my_len} cm！"
            )

    # Apply decay
    my_len = _apply_decay(my_len, store.config)
    oppo_len = _apply_decay(oppo_len, store.config)

    store.update_length(my_uid, my_len)
    store.update_length(oppo_uid, oppo_len)
    store._add_record(my_uid, "fencing", origin_my, my_len)
    store._add_record(oppo_uid, "fenced", origin_oppo, oppo_len)

    _set_cd(_fence_cd, my_uid, store.config.fence_cooldown)
    _set_cd(_fenced_cd, oppo_uid, store.config.fenced_protection)

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
