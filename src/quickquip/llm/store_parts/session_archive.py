"""SessionArchiveMixin：私聊会话归档的创建/恢复/管理。"""

from __future__ import annotations

from quickquip.llm.store_parts._base import _utc_now


class SessionArchiveMixin:
    """会话归档域。依赖 _StoreBase 的 _connect / _unavailable。

    archive_conversation_messages / restore_conversation_messages 直接操作
    conversation_messages 表（改 group_id 前缀），不调用 ConversationStoreMixin 方法。
    """

    def get_next_archive_number(self, user_id: str) -> int:
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        private_key = f"private:{user_id}"
        archive_key = f"archive:{user_id}:{archive_number}"
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE conversation_messages SET group_id = ? WHERE group_id = ?",
                (archive_key, private_key),
            )
            return int(cursor.rowcount)

    def restore_conversation_messages(self, user_id: str, archive_number: int) -> int:
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        private_key = f"private:{user_id}"
        archive_key = f"archive:{user_id}:{archive_number}"
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE conversation_messages SET group_id = ? WHERE group_id = ?",
                (private_key, archive_key),
            )
            return int(cursor.rowcount)

    def get_session_archive(self, user_id: str, archive_number: int) -> dict | None:
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(archive_number) AS mx FROM session_archives WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None or row["mx"] is None:
            return None
        return int(row["mx"])

    def delete_session_archive(self, user_id: str, archive_number: int) -> bool:
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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
