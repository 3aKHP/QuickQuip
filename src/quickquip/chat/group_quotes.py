from __future__ import annotations

from quickquip.common.identity_sources import identities, IdentitySnapshot
from quickquip.common.record_content import migrate, plain, project, render, save_parts, validate, matches

import logging
import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quickquip.llm.identity import IdentityIndex

logger = logging.getLogger(__name__)

_UNKNOWN_SNAPSHOT_NAMES = {"", "未知"}

_QUOTE_ROW_COLUMNS = (
    "id, group_id, quoted_user_id, quoted_sender_name,"
    " content, saved_by_user_id, saved_at, group_seq, content_parts_json"
)


def resolve_quote_display_name(
    quoted_user_id: str | int,
    snapshot_name: str,
    *,
    user_names: Mapping[str, str] | None = None,
    identity_index: IdentityIndex | None = None,
) -> tuple[str, bool]:
    """解析语录发言人的展示名，返回 ``(展示名, 是否与收藏时快照不同)``。

    名称来源优先级：身份资料规范名 → stats_tracker 最新群名片 → 库内快照。
    快照缺失或为占位名时视为无原名，仅返回解析名。
    """
    snapshot = str(snapshot_name or "").strip()
    uid = str(quoted_user_id or "").strip()
    if not uid:
        return snapshot, False

    resolved = IdentitySnapshot(identity_index or IdentitySnapshot().index, dict(user_names or {})).name(uid, snapshot if snapshot not in _UNKNOWN_SNAPSHOT_NAMES else "")
    if snapshot in {*_UNKNOWN_SNAPSHOT_NAMES, uid, f"QQ{uid}"} or resolved == snapshot:
        return resolved, False
    return resolved, True


def attach_sender_display(
    rows: list[dict],
    *,
    user_names: Mapping[str, str] | None = None,
    identity_index: IdentityIndex | None = None,
) -> list[dict]:
    """逐行附加 ``sender_display``/``sender_changed``，供 Web API 富化使用。"""
    snapshot = IdentitySnapshot(identity_index or IdentitySnapshot().index, dict(user_names or {}))
    for row in rows:
        row.update(project(row, snapshot))
        resolved, changed = resolve_quote_display_name(
            row.get("quoted_user_id", ""), row.get("quoted_sender_name", ""),
            user_names=user_names, identity_index=identity_index,
        )
        row["sender_display"] = resolved
        row["sender_changed"] = changed
    return rows


class GroupQuoteStore:
    def __init__(
        self,
        db_path: str | Path,
        *,
        recent_random_window_seconds: int = 600,
        time_func: Callable[[], float] = time.time,
    ):
        self._db: sqlite3.Connection | None = None
        self._closed = False
        self._path = Path(db_path)
        self._recent_random_window_seconds = max(1, int(recent_random_window_seconds))
        self._time = time_func
        self._recent_random_ids: dict[str, list[tuple[int, float]]] = {}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._unavailable = False
        try:
            self._db = sqlite3.connect(str(self._path), check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS quotes (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id            TEXT NOT NULL,
                    quoted_user_id      TEXT NOT NULL DEFAULT '',
                    quoted_sender_name  TEXT NOT NULL DEFAULT '',
                    content             TEXT NOT NULL,
                    saved_by_user_id    TEXT NOT NULL DEFAULT '',
                    saved_at            INTEGER NOT NULL,
                    group_seq           INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_quotes_group
                    ON quotes(group_id, id);
            """)
            self._migrate()
            migrate(self._db, "quotes")
            self._db.commit()
        except sqlite3.Error as exc:
            logger.error("GroupQuoteStore 数据库初始化失败 (%s)：%s", self._path, exc)
            self._unavailable = True

    def _migrate(self) -> None:
        try:
            self._db.execute("SELECT group_seq FROM quotes LIMIT 0")
        except sqlite3.OperationalError:
            self._db.execute(
                "ALTER TABLE quotes ADD COLUMN group_seq INTEGER NOT NULL DEFAULT 0"
            )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_quotes_group_seq ON quotes(group_id, group_seq)"
        )
        # backfill group_seq for rows that still have 0
        rows = self._db.execute(
            "SELECT id, group_id FROM quotes WHERE group_seq = 0 ORDER BY id"
        ).fetchall()
        if rows:
            from collections import defaultdict
            counters: dict[str, int] = defaultdict(int)
            for row in rows:
                gid = str(row[1])
                counters[gid] += 1
                self._db.execute(
                    "UPDATE quotes SET group_seq = ? WHERE id = ?",
                    (counters[gid], row[0]),
                )

    def add(
        self,
        group_id: str | int,
        quoted_user_id: str | int,
        quoted_sender_name: str,
        content: str,
        saved_by_user_id: str | int,
        *, content_parts: dict | None = None,
    ) -> int:
        if self._unavailable:
            raise RuntimeError("群语录 数据库不可用")
        body = validate(content_parts, 500) if content_parts is not None else plain(content)
        if content_parts is not None:
            content = render(body)
        gid = str(group_id)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute(
                "SELECT COALESCE(MAX(group_seq), 0) + 1 FROM quotes WHERE group_id = ?",
                (gid,),
            ).fetchone()
            next_seq = int(row[0]) if row else 1
            cur = self._db.execute(
                "INSERT INTO quotes"
                " (group_id, quoted_user_id, quoted_sender_name, content, saved_by_user_id, saved_at, group_seq)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (gid, str(quoted_user_id), quoted_sender_name, content,
                 str(saved_by_user_id), int(self._time()), next_seq),
            )
            save_parts(self._db, "quotes", cur.lastrowid, gid, body)
        return cur.lastrowid  # type: ignore[return-value]

    def _remember_random(self, group_id: str, quote_id: int) -> None:
        now = self._time()
        cutoff = now - self._recent_random_window_seconds
        recent = [
            (item_id, ts)
            for item_id, ts in self._recent_random_ids.get(group_id, [])
            if ts >= cutoff
        ]
        recent.append((quote_id, now))
        self._recent_random_ids[group_id] = recent

    def _recent_ids(self, group_id: str) -> set[int]:
        now = self._time()
        cutoff = now - self._recent_random_window_seconds
        recent = [
            (item_id, ts)
            for item_id, ts in self._recent_random_ids.get(group_id, [])
            if ts >= cutoff
        ]
        if recent:
            self._recent_random_ids[group_id] = recent
        else:
            self._recent_random_ids.pop(group_id, None)
        return {item_id for item_id, _ in recent}

    def random(self, group_id: str | int, *, identity_snapshot=None) -> dict | None:
        if self._unavailable:
            raise RuntimeError("群语录 数据库不可用")
        group_key = str(group_id)
        recent_ids = self._recent_ids(group_key)
        row = None
        if recent_ids:
            placeholders = ",".join("?" for _ in recent_ids)
            row = self._db.execute(
                "SELECT id, group_seq, quoted_user_id, quoted_sender_name, content, saved_at, content_parts_json"
                f" FROM quotes WHERE group_id=? AND id NOT IN ({placeholders})"
                " ORDER BY RANDOM() LIMIT 1",
                (group_key, *recent_ids),
            ).fetchone()

        if row is None:
            if recent_ids:
                self._recent_random_ids.pop(group_key, None)
            row = self._db.execute(
                "SELECT id, group_seq, quoted_user_id, quoted_sender_name, content, saved_at, content_parts_json"
                " FROM quotes WHERE group_id=? ORDER BY RANDOM() LIMIT 1",
                (group_key,),
            ).fetchone()

        if not row:
            return None

        self._remember_random(group_key, int(row[0]))
        return project(dict(row), identity_snapshot or getattr(self, "identity_repository", identities).snapshot(group_id))

    def clear_recent_random_history(self, group_id: str | int) -> None:
        self._recent_random_ids.pop(str(group_id), None)

    def recent_random_count(self, group_id: str | int) -> int:
        return len(self._recent_ids(str(group_id)))

    def close(self) -> None:
        if self._closed or self._db is None:
            return
        self._db.close()
        self._db = None
        self._closed = True

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def count(self, group_id: str | int) -> int:
        if self._unavailable:
            raise RuntimeError("群语录 数据库不可用")
        row = self._db.execute(
            "SELECT COUNT(*) FROM quotes WHERE group_id=?",
            (str(group_id),),
        ).fetchone()
        return row[0] if row else 0

    def get_by_seq(self, group_id: str | int, seq: int, *, identity_snapshot=None) -> dict | None:
        if self._unavailable:
            raise RuntimeError("群语录 数据库不可用")
        row = self._db.execute(
            f"SELECT {_QUOTE_ROW_COLUMNS}"
            " FROM quotes WHERE group_id=? AND group_seq=?",
            (str(group_id), int(seq)),
        ).fetchone()
        if not row:
            return None
        return project(row, identity_snapshot or getattr(self, "identity_repository", identities).snapshot(group_id))

    def search(
        self, group_id: str | int, keyword: str,
        offset: int = 0, limit: int = 50,
        identity_snapshot: IdentitySnapshot | None = None,
    ) -> tuple[list[dict], int]:
        if self._unavailable:
            raise RuntimeError("群语录 数据库不可用")
        snapshot = identity_snapshot or getattr(self, "identity_repository", identities).snapshot(group_id)
        rows = self._db.execute(f"SELECT {_QUOTE_ROW_COLUMNS} FROM quotes WHERE group_id=? ORDER BY id DESC", (str(group_id),))
        result, total = [], 0
        for row in rows:
            if matches(dict(row), keyword, snapshot):
                if offset <= total < offset + limit:
                    result.append(project(row, snapshot))
                total += 1
        return result, total

    def search_by_sender(
        self, group_id: str | int, *,
        user_ids: Sequence[str | int] = (),
        name_pattern: str = "",
        offset: int = 0, limit: int = 50,
        identity_snapshot: IdentitySnapshot | None = None,
    ) -> tuple[list[dict], int]:
        """按发言人检索：精确 QQ 号匹配与名称模糊匹配可组合，均为空时返回空。"""
        if self._unavailable:
            raise RuntimeError("群语录 数据库不可用")
        gid = str(group_id)
        ids = [str(u) for u in user_ids if str(u)]
        pattern = f"%{name_pattern}%" if name_pattern else ""
        if not ids and not pattern:
            return [], 0

        conditions = []
        params: list[object] = [gid]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            conditions.append(f"quoted_user_id IN ({placeholders})")
            params.extend(ids)
        if pattern:
            conditions.append("quoted_sender_name LIKE ?")
            params.append(pattern)
        where = f" WHERE group_id=? AND ({' OR '.join(conditions)})"

        rows = self._db.execute(
            f"SELECT {_QUOTE_ROW_COLUMNS}"
            f" FROM quotes{where} ORDER BY id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        total_row = self._db.execute(
            f"SELECT COUNT(*) AS c FROM quotes{where}", params,
        ).fetchone()
        snapshot = identity_snapshot or getattr(self, "identity_repository", identities).snapshot(group_id)
        return [project(r, snapshot) for r in rows], int(total_row["c"]) if total_row else 0

    def delete(self, quote_id: int) -> bool:
        if self._unavailable:
            raise RuntimeError("群语录 数据库不可用")
        cur = self._db.execute(
            "DELETE FROM quotes WHERE id=?",
            (int(quote_id),),
        )
        self._db.commit()
        return cur.rowcount > 0

    def list_quotes(
        self, group_id: str | int,
        offset: int = 0, limit: int = 50, keyword: str = "",
        *, identity_snapshot: IdentitySnapshot | None = None,
    ) -> tuple[list[dict], int]:
        if self._unavailable:
            raise RuntimeError("群语录 数据库不可用")
        gid = str(group_id)
        if keyword:
            return self.search(gid, keyword, offset, limit, identity_snapshot)
        rows = self._db.execute(
            f"SELECT {_QUOTE_ROW_COLUMNS}"
            " FROM quotes WHERE group_id=?"
            " ORDER BY id DESC LIMIT ? OFFSET ?",
            (gid, limit, offset),
        ).fetchall()
        total_row = self._db.execute(
            "SELECT COUNT(*) AS c FROM quotes WHERE group_id=?",
            (gid,),
        ).fetchone()
        snapshot = identity_snapshot or getattr(self, "identity_repository", identities).snapshot(group_id)
        return [project(r, snapshot) for r in rows], int(total_row["c"]) if total_row else 0

    def groups(self) -> list[dict]:
        if self._unavailable:
            raise RuntimeError("群语录 数据库不可用")
        rows = self._db.execute(
            "SELECT group_id, COUNT(*) AS count, MAX(id) AS latest_id"
            " FROM quotes GROUP BY group_id ORDER BY latest_id DESC"
        ).fetchall()
        return [{"group_id": r[0], "count": int(r[1])} for r in rows]
