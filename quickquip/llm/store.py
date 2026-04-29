from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import sqlite3


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_query_tokens(query: str) -> list[str]:
    normalized = query.strip()
    if not normalized:
        return []

    tokens: list[str] = []
    seen: set[str] = set()

    def _push(token: str) -> None:
        token = token.strip()
        if len(token) < 2 or token in seen:
            return
        seen.add(token)
        tokens.append(token)

    for part in re.findall(r"[A-Za-z0-9_]+", normalized):
        _push(part.lower())

    for part in re.findall(r"[\u4e00-\u9fff]+", normalized):
        _push(part)
        if len(part) >= 2:
            _push(part[:2])
            _push(part[-2:])
        if len(part) >= 4:
            for index in range(len(part) - 1):
                _push(part[index:index + 2])

    return tokens[:12]


@dataclass(slots=True)
class GroupSettingsOverride:
    enabled: bool | None = None
    memory_enabled: bool | None = None
    auto_memory_enabled: bool | None = None
    provider_id: str | None = None
    model: str | None = None
    persona_id: str | None = None
    trigger_prefix: str | None = None
    allow_prefix: bool | None = None
    allow_at: bool | None = None
    history_limit: int | None = None


class LLMStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
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
                CREATE TABLE IF NOT EXISTS group_settings (
                    group_id TEXT PRIMARY KEY,
                    enabled INTEGER,
                    memory_enabled INTEGER,
                    provider_id TEXT,
                    model TEXT,
                    persona_id TEXT,
                    trigger_prefix TEXT,
                    allow_prefix INTEGER,
                    allow_at INTEGER,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    user_id TEXT,
                    sender_name TEXT,
                    canonical_name TEXT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_conversation_group_id
                ON conversation_messages(group_id, id);

                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    user_id TEXT,
                    scope TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL DEFAULT 'manual',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_memories_group_id
                ON memories(group_id, id);

                CREATE TABLE IF NOT EXISTS session_archives (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id         TEXT NOT NULL,
                    archive_number  INTEGER NOT NULL,
                    persona_id      TEXT,
                    preset          TEXT,
                    message_count   INTEGER NOT NULL DEFAULT 0,
                    created_at      TEXT NOT NULL,
                    ended_at        TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_session_archives_user_number
                ON session_archives(user_id, archive_number);
                """
            )
            existing_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(group_settings)").fetchall()
            }
            if "memory_enabled" not in existing_columns:
                conn.execute("ALTER TABLE group_settings ADD COLUMN memory_enabled INTEGER")
            if "history_limit" not in existing_columns:
                conn.execute("ALTER TABLE group_settings ADD COLUMN history_limit INTEGER")
            if "auto_memory_enabled" not in existing_columns:
                conn.execute("ALTER TABLE group_settings ADD COLUMN auto_memory_enabled INTEGER")
            conversation_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(conversation_messages)").fetchall()
            }
            if "sender_name" not in conversation_columns:
                conn.execute("ALTER TABLE conversation_messages ADD COLUMN sender_name TEXT")
            if "canonical_name" not in conversation_columns:
                conn.execute("ALTER TABLE conversation_messages ADD COLUMN canonical_name TEXT")
            if "message_id" not in conversation_columns:
                conn.execute("ALTER TABLE conversation_messages ADD COLUMN message_id TEXT")
            if "raw_content" not in conversation_columns:
                conn.execute("ALTER TABLE conversation_messages ADD COLUMN raw_content TEXT")

    def get_group_settings(self, group_id: int | str) -> GroupSettingsOverride:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT enabled, memory_enabled, auto_memory_enabled, provider_id, model, persona_id, trigger_prefix, allow_prefix, allow_at, history_limit
                FROM group_settings
                WHERE group_id = ?
                """,
                (str(group_id),),
            ).fetchone()
        if row is None:
            return GroupSettingsOverride()
        return GroupSettingsOverride(
            enabled=None if row["enabled"] is None else bool(row["enabled"]),
            memory_enabled=None if row["memory_enabled"] is None else bool(row["memory_enabled"]),
            auto_memory_enabled=None if row["auto_memory_enabled"] is None else bool(row["auto_memory_enabled"]),
            provider_id=row["provider_id"],
            model=row["model"],
            persona_id=row["persona_id"],
            trigger_prefix=row["trigger_prefix"],
            allow_prefix=None if row["allow_prefix"] is None else bool(row["allow_prefix"]),
            allow_at=None if row["allow_at"] is None else bool(row["allow_at"]),
            history_limit=None if row["history_limit"] is None else int(row["history_limit"]),
        )

    def update_group_settings(self, group_id: int | str, **fields: object) -> None:
        group_key = str(group_id)
        allowed_fields = {
            "enabled",
            "memory_enabled",
            "auto_memory_enabled",
            "provider_id",
            "model",
            "persona_id",
            "trigger_prefix",
            "allow_prefix",
            "allow_at",
            "history_limit",
        }
        payload = {key: value for key, value in fields.items() if key in allowed_fields}
        if not payload:
            return
        payload["updated_at"] = _utc_now()

        with self._connect() as conn:
            current = conn.execute(
                "SELECT group_id FROM group_settings WHERE group_id = ?",
                (group_key,),
            ).fetchone()

            if current is None:
                columns = ["group_id", *payload.keys()]
                values = [group_key, *payload.values()]
                placeholders = ", ".join("?" for _ in columns)
                conn.execute(
                    f"INSERT INTO group_settings ({', '.join(columns)}) VALUES ({placeholders})",
                    values,
                )
                return

            assignments = ", ".join(f"{key} = ?" for key in payload)
            conn.execute(
                f"UPDATE group_settings SET {assignments} WHERE group_id = ?",
                [*payload.values(), group_key],
            )

    def append_conversation_message(
        self,
        group_id: int | str,
        user_id: int | str | None,
        role: str,
        content: str,
        *,
        sender_name: str = "",
        canonical_name: str = "",
        message_id: str | None = None,
        raw_content: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_messages (group_id, user_id, sender_name, canonical_name, role, content, message_id, raw_content, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(group_id),
                    None if user_id is None else str(user_id),
                    sender_name.strip() or None,
                    canonical_name.strip() or None,
                    role,
                    content,
                    message_id,
                    raw_content or None,
                    _utc_now(),
                ),
            )

    def list_recent_conversation_messages(
        self,
        group_id: int | str,
        limit: int,
    ) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT user_id, sender_name, canonical_name, role, content, raw_content
                FROM conversation_messages
                WHERE group_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (str(group_id), int(limit)),
            ).fetchall()
        return [
            {
                "user_id": "" if row["user_id"] is None else str(row["user_id"]),
                "sender_name": "" if row["sender_name"] is None else str(row["sender_name"]),
                "canonical_name": "" if row["canonical_name"] is None else str(row["canonical_name"]),
                "role": row["role"],
                "content": row["content"],
                "raw_content": "" if row["raw_content"] is None else str(row["raw_content"]),
            }
            for row in reversed(rows)
        ]

    def prune_conversation_messages(self, group_id: int | str, keep_last: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM conversation_messages
                WHERE group_id = ?
                  AND id NOT IN (
                      SELECT id FROM conversation_messages
                      WHERE group_id = ?
                      ORDER BY id DESC
                      LIMIT ?
                  )
                """,
                (str(group_id), str(group_id), int(keep_last)),
            )

    def count_conversation_messages(self, group_id: int | str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM conversation_messages
                WHERE group_id = ?
                """,
                (str(group_id),),
            ).fetchone()
        return int(row["total"]) if row is not None else 0

    def clear_conversation_messages(self, group_id: int | str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM conversation_messages
                WHERE group_id = ?
                """,
                (str(group_id),),
            )
            return int(cursor.rowcount)

    def delete_conversation_message_by_message_id(self, group_id: int | str, message_id: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM conversation_messages
                WHERE group_id = ? AND message_id = ?
                """,
                (str(group_id), str(message_id)),
            )
            return int(cursor.rowcount)

    def update_last_assistant_message_id(self, group_id: int | str, message_id: str) -> None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM conversation_messages
                WHERE group_id = ? AND role = 'assistant' AND message_id IS NULL
                ORDER BY id DESC
                LIMIT 1
                """,
                (str(group_id),),
            ).fetchone()
            if row is not None:
                conn.execute(
                    "UPDATE conversation_messages SET message_id = ? WHERE id = ?",
                    (str(message_id), row["id"]),
                )

    def add_memory(
        self,
        group_id: int | str,
        content: str,
        *,
        scope: str = "group",
        user_id: int | str | None = None,
        tags: list[str] | None = None,
        source: str = "manual",
        confidence: float = 1.0,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO memories (group_id, user_id, scope, content, tags_json, source, confidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(group_id),
                    None if user_id is None else str(user_id),
                    scope,
                    content,
                    json.dumps(tags or [], ensure_ascii=False),
                    source,
                    confidence,
                    _utc_now(),
                    _utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def list_memories(
        self,
        group_id: int | str,
        *,
        limit: int = 10,
        keyword: str | None = None,
    ) -> list[dict[str, object]]:
        params: list[object] = [str(group_id)]
        sql = """
            SELECT id, scope, user_id, content, tags_json, source, confidence, created_at, updated_at
            FROM memories
            WHERE group_id = ?
        """
        if keyword:
            sql += " AND content LIKE ?"
            params.append(f"%{keyword}%")
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "id": row["id"],
                "scope": row["scope"],
                "user_id": row["user_id"],
                "content": row["content"],
                "tags": json.loads(row["tags_json"]),
                "source": row["source"],
                "confidence": row["confidence"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def search_memories(
        self,
        group_id: int | str,
        *,
        user_id: int | str | None,
        query: str,
        limit: int,
        scope: str | None = None,
    ) -> list[dict[str, object]]:
        tokens = _build_query_tokens(query)
        scope_clause: str
        params: list[object]
        if scope == "user":
            scope_clause = "scope = 'user' AND user_id = ?"
            params = [str(group_id), None if user_id is None else str(user_id)]
        else:
            scope_clause = "scope = 'group' OR (scope = 'user' AND user_id = ?)"
            params = [str(group_id), None if user_id is None else str(user_id)]
        sql = f"""
            SELECT id, scope, user_id, content, tags_json, source, confidence, created_at, updated_at
            FROM memories
            WHERE group_id = ?
              AND ({scope_clause})
        """
        if tokens:
            sql += " AND (" + " OR ".join("content LIKE ?" for _ in tokens) + ")"
            params.extend(f"%{token}%" for token in tokens)
        sql += " ORDER BY confidence DESC, id DESC LIMIT ?"
        params.append(int(limit))

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "id": row["id"],
                "scope": row["scope"],
                "user_id": row["user_id"],
                "content": row["content"],
                "tags": json.loads(row["tags_json"]),
                "source": row["source"],
                "confidence": row["confidence"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def delete_memories(self, group_id: int | str, keyword: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM memories
                WHERE group_id = ? AND content LIKE ?
                """,
                (str(group_id), f"%{keyword}%"),
            )
            return int(cursor.rowcount)

    def prune_memories(self, group_id: int | str, keep_last: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM memories
                WHERE group_id = ?
                  AND id NOT IN (
                      SELECT id FROM memories
                      WHERE group_id = ?
                      ORDER BY id DESC
                      LIMIT ?
                  )
                """,
                (str(group_id), str(group_id), int(keep_last)),
            )

    def clear_memories(self, group_id: int | str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM memories
                WHERE group_id = ?
                """,
                (str(group_id),),
            )
            return int(cursor.rowcount)

    def count_memories(self, group_id: int | str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM memories
                WHERE group_id = ?
                """,
                (str(group_id),),
            ).fetchone()
        return int(row["total"]) if row is not None else 0

    # ── session archives ──

    def get_next_archive_number(self, user_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(archive_number) AS mx FROM session_archives WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        current = row["mx"] if row is not None and row["mx"] is not None else 0
        return int(current) + 1

    def create_session_archive(
        self,
        user_id: str,
        archive_number: int,
        *,
        persona_id: str | None = None,
        preset: str | None = None,
        message_count: int = 0,
        created_at: str = "",
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO session_archives (user_id, archive_number, persona_id, preset, message_count, created_at, ended_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    archive_number,
                    persona_id,
                    preset or None,
                    message_count,
                    created_at or _utc_now(),
                    _utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def archive_conversation_messages(self, user_id: str, archive_number: int) -> int:
        private_key = f"private:{user_id}"
        archive_key = f"archive:{user_id}:{archive_number}"
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE conversation_messages SET group_id = ? WHERE group_id = ?",
                (archive_key, private_key),
            )
            return int(cursor.rowcount)

    def restore_conversation_messages(self, user_id: str, archive_number: int) -> int:
        private_key = f"private:{user_id}"
        archive_key = f"archive:{user_id}:{archive_number}"
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE conversation_messages SET group_id = ? WHERE group_id = ?",
                (private_key, archive_key),
            )
            return int(cursor.rowcount)

    def get_session_archive(self, user_id: str, archive_number: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, user_id, archive_number, persona_id, preset, message_count, created_at, ended_at
                FROM session_archives
                WHERE user_id = ? AND archive_number = ?
                """,
                (user_id, archive_number),
            ).fetchone()
        if row is None:
            return None
        return {k: row[k] for k in row.keys()}

    def list_session_archives(self, user_id: str, *, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, archive_number, persona_id, preset, message_count, created_at, ended_at
                FROM session_archives
                WHERE user_id = ?
                ORDER BY archive_number DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [{k: row[k] for k in row.keys()} for row in rows]

    def get_latest_archive_number(self, user_id: str) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(archive_number) AS mx FROM session_archives WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None or row["mx"] is None:
            return None
        return int(row["mx"])

    def delete_session_archive(self, user_id: str, archive_number: int) -> bool:
        archive_key = f"archive:{user_id}:{archive_number}"
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM conversation_messages WHERE group_id = ?",
                (archive_key,),
            )
            cursor = conn.execute(
                "DELETE FROM session_archives WHERE user_id = ? AND archive_number = ?",
                (user_id, archive_number),
            )
            return int(cursor.rowcount) > 0

    def get_earliest_message_time(self, group_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MIN(created_at) AS earliest FROM conversation_messages WHERE group_id = ?",
                (group_id,),
            ).fetchone()
        if row is None or row["earliest"] is None:
            return ""
        return str(row["earliest"])
