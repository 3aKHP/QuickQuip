from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from quickquip.games.config import EconomyConfig


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GameEconomyStore:
    """SQLite-backed gold economy for group games.

    Manages gold accounts, daily sign-in with streak tracking, and
    gold transfer operations used by individual games.

    All gold operations on a single account are atomic (SQLite transactions).
    Cross-account transfers use explicit ``BEGIN IMMEDIATE`` for safety.
    """

    def __init__(self, path: str = "data/game_economy.db", config: EconomyConfig | None = None):
        self.path = Path(path)
        self.config = config or EconomyConfig()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def connect(self) -> sqlite3.Connection:
        """Return a new SQLite connection with row_factory set.

        Public for use by web-admin routes and other external consumers
        that need direct query access beyond the standard API.
        """
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    _connect = connect  # internal alias for backward compatibility

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS gold_accounts (
                    user_id        TEXT NOT NULL,
                    group_id       TEXT NOT NULL,
                    gold           INTEGER NOT NULL DEFAULT 0,
                    affection      INTEGER NOT NULL DEFAULT 0,
                    sign_streak    INTEGER NOT NULL DEFAULT 0,
                    last_sign_date TEXT NOT NULL DEFAULT '',
                    created_at     TEXT NOT NULL,
                    PRIMARY KEY (user_id, group_id)
                );
                """
            )

    # ── account helpers ──────────────────────────────────────────────────

    def _ensure_account(self, conn: sqlite3.Connection, user_id: str, group_id: str) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO gold_accounts (user_id, group_id, created_at)
            VALUES (?, ?, ?)
            """,
            (str(user_id), str(group_id), _utc_now()),
        )

    # ── balance / rank ───────────────────────────────────────────────────

    def get_balance(self, user_id: str, group_id: str) -> dict:
        """Return {gold, affection, sign_streak, last_sign_date} for a user."""
        with self._connect() as conn:
            self._ensure_account(conn, user_id, group_id)
            row = conn.execute(
                """
                SELECT gold, affection, sign_streak, last_sign_date
                FROM gold_accounts
                WHERE user_id = ? AND group_id = ?
                """,
                (str(user_id), str(group_id)),
            ).fetchone()
        return {
            "gold": row["gold"],
            "affection": row["affection"],
            "sign_streak": row["sign_streak"],
            "last_sign_date": row["last_sign_date"],
        }

    def add_gold(self, user_id: str, group_id: str, amount: int) -> int:
        """Add *amount* gold to a user. Returns new balance."""
        with self._connect() as conn:
            self._ensure_account(conn, user_id, group_id)
            conn.execute(
                """
                UPDATE gold_accounts
                SET gold = gold + ?
                WHERE user_id = ? AND group_id = ?
                """,
                (amount, str(user_id), str(group_id)),
            )
            row = conn.execute(
                "SELECT gold FROM gold_accounts WHERE user_id = ? AND group_id = ?",
                (str(user_id), str(group_id)),
            ).fetchone()
        return row["gold"]

    def deduct_gold(self, user_id: str, group_id: str, amount: int) -> bool:
        """Deduct *amount* gold. Returns False if insufficient balance."""
        with self._connect() as conn:
            self._ensure_account(conn, user_id, group_id)
            cursor = conn.execute(
                """
                UPDATE gold_accounts
                SET gold = gold - ?
                WHERE user_id = ? AND group_id = ? AND gold >= ?
                """,
                (amount, str(user_id), str(group_id), amount),
            )
            return cursor.rowcount > 0

    def transfer_gold(
        self, from_user: str, to_user: str, group_id: str, amount: int
    ) -> bool:
        """Atomically transfer *amount* gold between two users in the same group.

        Returns False if *from_user* has insufficient balance.
        """
        gid = str(group_id)
        fu = str(from_user)
        tu = str(to_user)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_account(conn, fu, gid)
            self._ensure_account(conn, tu, gid)
            # Check balance
            row = conn.execute(
                "SELECT gold FROM gold_accounts WHERE user_id = ? AND group_id = ?",
                (fu, gid),
            ).fetchone()
            if row is None or row["gold"] < amount:
                conn.rollback()
                return False
            conn.execute(
                "UPDATE gold_accounts SET gold = gold - ? WHERE user_id = ? AND group_id = ?",
                (amount, fu, gid),
            )
            conn.execute(
                "UPDATE gold_accounts SET gold = gold + ? WHERE user_id = ? AND group_id = ?",
                (amount, tu, gid),
            )
            conn.commit()
        return True

    def get_rank(
        self, group_id: str, top_n: int = 10
    ) -> list[dict[str, object]]:
        """Return top *top_n* users by gold in *group_id*."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT user_id, gold, affection, sign_streak
                FROM gold_accounts
                WHERE group_id = ?
                ORDER BY gold DESC
                LIMIT ?
                """,
                (str(group_id), top_n),
            ).fetchall()
        return [{"user_id": r["user_id"], "gold": r["gold"], "affection": r["affection"], "sign_streak": r["sign_streak"]} for r in rows]

    # ── sign-in ──────────────────────────────────────────────────────────

    def sign_in(self, user_id: str, group_id: str, today: str = "") -> dict:
        """Perform daily sign-in. Returns {gold_earned, affection_gained, streak, message}.

        *today* should be ISO date string (YYYY-MM-DD). Uses UTC if empty.
        """
        if not today:
            today = date.today().isoformat()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_account(conn, user_id, group_id)
            row = conn.execute(
                """
                SELECT gold, affection, sign_streak, last_sign_date
                FROM gold_accounts
                WHERE user_id = ? AND group_id = ?
                """,
                (str(user_id), str(group_id)),
            ).fetchone()

            if row["last_sign_date"] == today:
                conn.rollback()
                return {
                    "gold_earned": 0,
                    "affection_gained": 0,
                    "streak": row["sign_streak"],
                    "total_gold": row["gold"],
                    "total_affection": row["affection"],
                    "message": "今日已签过到了，明天再来吧！",
                }

            # Calculate streak
            yesterday = _yesterday(today)
            streak = row["sign_streak"] + 1 if row["last_sign_date"] == yesterday else 1

            # Reward formula: base + streak bonus (capped at max)
            cfg = self.config
            streak_bonus = min((streak - 1) * cfg.sign_streak_bonus, cfg.sign_max_streak_bonus)
            gold_earned = cfg.sign_base_gold + streak_bonus
            affection_gained = cfg.affection_per_sign

            conn.execute(
                """
                UPDATE gold_accounts
                SET gold = gold + ?,
                    affection = affection + ?,
                    sign_streak = ?,
                    last_sign_date = ?
                WHERE user_id = ? AND group_id = ?
                """,
                (gold_earned, affection_gained, streak, today, str(user_id), str(group_id)),
            )
            conn.commit()

        return {
            "gold_earned": gold_earned,
            "affection_gained": affection_gained,
            "streak": streak,
            "total_gold": row["gold"] + gold_earned,
            "total_affection": row["affection"] + affection_gained,
            "message": _sign_message(gold_earned, streak),
        }

    # ── affection ────────────────────────────────────────────────────────

    def get_affection(self, user_id: str, group_id: str) -> int:
        """Return the user's affection level in this group."""
        with self._connect() as conn:
            self._ensure_account(conn, user_id, group_id)
            row = conn.execute(
                "SELECT affection FROM gold_accounts WHERE user_id = ? AND group_id = ?",
                (str(user_id), str(group_id)),
            ).fetchone()
        return row["affection"] if row else 0

    def add_affection(self, user_id: str, group_id: str, amount: int) -> int:
        """Add *amount* affection. Returns new total."""
        with self._connect() as conn:
            self._ensure_account(conn, user_id, group_id)
            conn.execute(
                "UPDATE gold_accounts SET affection = affection + ? WHERE user_id = ? AND group_id = ?",
                (amount, str(user_id), str(group_id)),
            )
            row = conn.execute(
                "SELECT affection FROM gold_accounts WHERE user_id = ? AND group_id = ?",
                (str(user_id), str(group_id)),
            ).fetchone()
        return row["affection"]


def _yesterday(today: str) -> str:
    try:
        dt = datetime.strptime(today, "%Y-%m-%d").date()
        return (dt - timedelta(days=1)).isoformat()
    except ValueError:
        return ""


def _sign_message(gold: int, streak: int) -> str:
    if streak >= 30:
        return f"签到成功！+{gold} 金币 🔥 已连续签到 {streak} 天，你是真正的卷王！"
    if streak >= 7:
        return f"签到成功！+{gold} 金币，连续签到 {streak} 天，势头不错！"
    if streak >= 3:
        return f"签到成功！+{gold} 金币，连续签到 {streak} 天了~"
    if streak == 1:
        return f"签到成功！+{gold} 金币，明天继续来领更多哦！"
    return f"签到成功！+{gold} 金币，已连续签到 {streak} 天"
