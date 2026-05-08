"""SQLite-backed persistent store for 牛牛大作战 user data."""

from __future__ import annotations

import random
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from quickquip.games.config import NiuNiuConfig


def _roll_lognormal(sigma: float) -> float:
    """Roll a log10-symmetric luck value: lg(x) ~ N(0, σ).

    No hard bounds — extreme values (1e-9 or 1e9) are rare but possible.
    σ=1 → ±1σ = [0.1, 10], median = 1.0.
    """
    return round(10.0 ** random.gauss(0.0, sigma), 2)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _random_initial_length(store: NiuNiuStore) -> float:
    """30th-percentile initial length × 0.9, or 10.0 for the first user."""
    with store._connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM niuniu_users").fetchone()
        total = row["c"] if row else 0
    if total == 0:
        return 10.0
    idx = min(int(total * 0.3), total - 1)
    with store._connect() as conn:
        row = conn.execute(
            "SELECT length FROM niuniu_users ORDER BY length ASC LIMIT 1 OFFSET ?",
            (idx,),
        ).fetchone()
    if row is None:
        return 10.0
    return round(row["length"] * 0.9, 2)


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
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    _connect = connect

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS niuniu_users (
                    uid        TEXT PRIMARY KEY,
                    length     REAL NOT NULL DEFAULT 0,
                    luck       REAL NOT NULL DEFAULT 1.0,
                    luck_date  TEXT NOT NULL DEFAULT '',
                    fence_luck REAL NOT NULL DEFAULT 1.0,
                    fence_luck_date TEXT NOT NULL DEFAULT '',
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
        self._migrate()

    def _migrate(self) -> None:
        """Add columns added after the initial schema release."""
        with self._connect() as conn:
            cur = conn.execute("PRAGMA table_info('niuniu_users')")
            cols = {r["name"] for r in cur.fetchall()}
            if "luck" not in cols:
                conn.execute(
                    "ALTER TABLE niuniu_users ADD COLUMN luck REAL NOT NULL DEFAULT 1.0"
                )
            if "luck_date" not in cols:
                conn.execute(
                    "ALTER TABLE niuniu_users ADD COLUMN luck_date TEXT NOT NULL DEFAULT ''"
                )
            if "fence_luck" not in cols:
                conn.execute(
                    "ALTER TABLE niuniu_users ADD COLUMN fence_luck REAL NOT NULL DEFAULT 1.0"
                )
            if "fence_luck_date" not in cols:
                conn.execute(
                    "ALTER TABLE niuniu_users ADD COLUMN fence_luck_date TEXT NOT NULL DEFAULT ''"
                )

    # ── daily glue luck (打胶运势) ──────────────────────────────────────

    @staticmethod
    def _today_str() -> str:
        return date.today().isoformat()

    def _roll_daily_glue_luck(self, uid: str) -> float:
        luck = _roll_lognormal(self.config.luck_sigma)
        today = self._today_str()
        with self._connect() as conn:
            conn.execute(
                "UPDATE niuniu_users SET luck = ?, luck_date = ? WHERE uid = ?",
                (luck, today, uid),
            )
        return luck

    def get_glue_luck(self, uid: str) -> float:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT luck, luck_date FROM niuniu_users WHERE uid = ?", (uid,)
            ).fetchone()
        if row is None:
            return 1.0
        if row["luck_date"] != self._today_str():
            return self._roll_daily_glue_luck(uid)
        return row["luck"]

    def set_glue_luck(self, uid: str, value: float) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE niuniu_users SET luck = ?, luck_date = ? WHERE uid = ?",
                (round(value, 2), self._today_str(), uid),
            )

    # ── daily fence luck (击剑运势) ────────────────────────────────────

    def _roll_daily_fence_luck(self, uid: str) -> float:
        luck = _roll_lognormal(self.config.fence_luck_sigma)
        today = self._today_str()
        with self._connect() as conn:
            conn.execute(
                "UPDATE niuniu_users SET fence_luck = ?, fence_luck_date = ? WHERE uid = ?",
                (luck, today, uid),
            )
        return luck

    def get_fence_luck(self, uid: str) -> float:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT fence_luck, fence_luck_date FROM niuniu_users WHERE uid = ?",
                (uid,),
            ).fetchone()
        if row is None:
            return 1.0
        if row["fence_luck_date"] != self._today_str():
            return self._roll_daily_fence_luck(uid)
        return row["fence_luck"]

    def set_fence_luck(self, uid: str, value: float) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE niuniu_users SET fence_luck = ?, fence_luck_date = ? WHERE uid = ?",
                (round(value, 2), self._today_str(), uid),
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
        cfg = self.config
        glue_luck = _roll_lognormal(cfg.luck_sigma)
        fence_luck = _roll_lognormal(cfg.fence_luck_sigma)
        today = self._today_str()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO niuniu_users (uid, length, luck, luck_date, fence_luck, fence_luck_date, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, length, glue_luck, today, fence_luck, today, now, now),
            )
        self._add_record(uid, "register", 0, length)
        return length

    def unsubscribe(self, uid: str) -> Optional[float]:
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
        """Rank by descending length (positive only)."""
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

    def rank_by_natural(self, limit: int = 10, user_ids: list[str] | None = None) -> list[dict]:
        """Rank all users by signed length descending."""
        with self._connect() as conn:
            if user_ids:
                placeholders = ",".join("?" for _ in user_ids)
                rows = conn.execute(
                    f"SELECT uid, length FROM niuniu_users WHERE uid IN ({placeholders}) ORDER BY length DESC LIMIT ?",
                    [*user_ids, limit],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT uid, length FROM niuniu_users ORDER BY length DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [{"uid": r["uid"], "length": r["length"]} for r in rows]

    def rank_by_absolute(self, limit: int = 10, user_ids: list[str] | None = None) -> list[dict]:
        """Rank all users by ABS(length) descending."""
        with self._connect() as conn:
            if user_ids:
                placeholders = ",".join("?" for _ in user_ids)
                rows = conn.execute(
                    f"SELECT uid, length FROM niuniu_users WHERE uid IN ({placeholders}) ORDER BY ABS(length) DESC LIMIT ?",
                    [*user_ids, limit],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT uid, length FROM niuniu_users ORDER BY ABS(length) DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [{"uid": r["uid"], "length": r["length"]} for r in rows]

    def get_rank_position(self, uid: str, type: str = "natural") -> int:
        """Return the 1-based rank of *uid*.

        *type* selects the ranking:
        - "natural":  signed length DESC across all users
        - "absolute": ABS(length) DESC across all users
        - "length":   among positive-length users only (-1 if length <= 0)
        - "depth":    among negative-length users only (-1 if length >= 0)
        """
        length = self.get_length(uid)
        if length is None:
            return -1

        with self._connect() as conn:
            if type == "natural":
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM niuniu_users WHERE length > ?",
                    (length,),
                ).fetchone()
            elif type == "absolute":
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM niuniu_users WHERE ABS(length) > ?",
                    (abs(length),),
                ).fetchone()
            elif type == "length":
                if length <= 0:
                    return -1
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM niuniu_users WHERE length > ? AND length > 0",
                    (length,),
                ).fetchone()
            elif type == "depth":
                if length >= 0:
                    return -1
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM niuniu_users WHERE length < ? AND length < 0",
                    (length,),
                ).fetchone()
            else:
                return -1
            return (row["c"] if row else 0) + 1
