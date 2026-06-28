"""ConversationStoreMixin：会话消息的增删改查。"""

from __future__ import annotations

from quickquip.llm.store_parts._base import _utc_now


class ConversationStoreMixin:
    """会话消息存储域。依赖 _StoreBase 的 _connect / _unavailable。"""

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
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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

    def get_earliest_message_time(self, group_id: str) -> str:
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MIN(created_at) AS earliest FROM conversation_messages WHERE group_id = ?",
                (group_id,),
            ).fetchone()
        if row is None or row["earliest"] is None:
            return ""
        return str(row["earliest"])
