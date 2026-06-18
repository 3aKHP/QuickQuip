"""MemoryStoreMixin：长期记忆的增删改查 + 分词搜索。"""

from __future__ import annotations

import json

from quickquip.llm.store_parts._base import _build_query_tokens, _utc_now


class MemoryStoreMixin:
    """记忆存储域。依赖 _StoreBase 的 _connect / _unavailable / _safe_load_tags。"""

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
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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
                "tags": self._safe_load_tags(row["tags_json"]),
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
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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
                "tags": self._safe_load_tags(row["tags_json"]),
                "source": row["source"],
                "confidence": row["confidence"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def delete_memories(self, group_id: int | str, keyword: str) -> int:
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
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
