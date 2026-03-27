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

    def get_group_settings(self, group_id: int | str) -> GroupSettingsOverride:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT enabled, memory_enabled, provider_id, model, persona_id, trigger_prefix, allow_prefix, allow_at, history_limit
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
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_messages (group_id, user_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(group_id), None if user_id is None else str(user_id), role, content, _utc_now()),
            )

    def list_recent_conversation_messages(
        self,
        group_id: int | str,
        limit: int,
    ) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content
                FROM conversation_messages
                WHERE group_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (str(group_id), int(limit)),
            ).fetchall()
        return [
            {"role": row["role"], "content": row["content"]}
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
    ) -> list[dict[str, object]]:
        tokens = _build_query_tokens(query)
        sql = """
            SELECT id, scope, user_id, content, tags_json, source, confidence, created_at, updated_at
            FROM memories
            WHERE group_id = ?
              AND (
                    scope = 'group'
                    OR (scope = 'user' AND user_id = ?)
                  )
        """
        params: list[object] = [str(group_id), None if user_id is None else str(user_id)]
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
