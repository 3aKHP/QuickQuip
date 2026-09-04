"""ConversationStoreMixin：会话消息的增删改查。"""

from __future__ import annotations

from quickquip.llm.store_parts._base import _utc_now


def _normalize_conversation_row(row) -> dict[str, str]:
    """会话行的公共归一化（NULL → 空串）。两个读方法共用，勿各自复制。"""
    return {
        "user_id": "" if row["user_id"] is None else str(row["user_id"]),
        "sender_name": "" if row["sender_name"] is None else str(row["sender_name"]),
        "canonical_name": "" if row["canonical_name"] is None else str(row["canonical_name"]),
        "role": row["role"],
        "content": row["content"],
        "raw_content": "" if row["raw_content"] is None else str(row["raw_content"]),
    }


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
        return [_normalize_conversation_row(row) for row in reversed(rows)]

    def list_conversation_messages_since(
        self,
        group_id: int | str,
        anchor_id: int,
        *,
        limit: int,
    ) -> list[dict[str, object]]:
        """会话纪元范围读：返回 ``id >= anchor_id`` 的行（ASC 正序，含 id/message_id）。

        与 ``list_recent_conversation_messages``（DESC LIMIT 尾读，auto_memory 专用）
        是两种读模式：主生成链路用锚点范围读保证纪元内前缀逐字节稳定。
        """
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, sender_name, canonical_name, role, content, message_id, raw_content
                FROM conversation_messages
                WHERE group_id = ? AND id >= ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (str(group_id), int(anchor_id), int(limit)),
            ).fetchall()
        return [
            {
                **_normalize_conversation_row(row),
                "id": int(row["id"]),
                "message_id": "" if row["message_id"] is None else str(row["message_id"]),
            }
            for row in rows
        ]

    def find_anchor_row_id_by_rows(self, group_id: int | str, keep_rows: int) -> int | None:
        """返回「保留最新 keep_rows 行」的锚点行 id（第 keep_rows 新的行）。

        总行数 <= keep_rows 时返回 None（无需锚定，从头读即可）。
        """
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        if keep_rows < 1:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM conversation_messages
                WHERE group_id = ?
                ORDER BY id DESC
                LIMIT 1 OFFSET ?
                """,
                (str(group_id), int(keep_rows) - 1),
            ).fetchone()
        return None if row is None else int(row["id"])

    def find_next_user_row_id(self, group_id: int | str, from_id: int) -> int | None:
        """返回 >= from_id 的第一条 user 行 id（锚点 pair 对齐用）；没有则 None。"""
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM conversation_messages
                WHERE group_id = ? AND id >= ? AND role = 'user'
                ORDER BY id ASC
                LIMIT 1
                """,
                (str(group_id), int(from_id)),
            ).fetchone()
        return None if row is None else int(row["id"])

    def crop_conversation_messages(
        self,
        group_id: int | str,
        *,
        floor_id: int | None,
        keep_last: int,
    ) -> None:
        """按纪元锚点裁剪：删除 floor_id 以下（所有纪元键都不再需要）或超出
        keep_last 硬上限的行。floor_id 取该 scope 所有纪元键的最老锚点；
        锚点缺失（None）时只按 keep_last 兜底，绝不按窗口重估删行——进程
        重启后懒初始化还要读旧行。
        """
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM conversation_messages
                WHERE group_id = ?
                  AND (
                      id < ?
                      OR id NOT IN (
                          SELECT id FROM conversation_messages
                          WHERE group_id = ?
                          ORDER BY id DESC
                          LIMIT ?
                      )
                  )
                """,
                (str(group_id), int(floor_id or 0), str(group_id), int(keep_last)),
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
