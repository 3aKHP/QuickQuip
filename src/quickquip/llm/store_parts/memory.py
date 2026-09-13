"""MemoryStoreMixin：长期记忆的增删改查 + 分词搜索。"""

from __future__ import annotations

import json

from quickquip.common.record_content import plain, project, render, validate
from quickquip.common.record_storage import save_parts
from quickquip.common.record_search import RecordQuery

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
        content_parts: dict | None = None,
    ) -> int:
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        body = validate(content_parts) if content_parts is not None else plain(content)
        if content_parts is not None:
            content = render(body)
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
            save_parts(conn, "memories", int(cursor.lastrowid), group_id, body)
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
        snapshot = self.identity_repository.snapshot(group_id)
        matcher = RecordQuery(keyword, snapshot)
        with self._connect() as conn:
            sql = "SELECT * FROM memories WHERE group_id=? ORDER BY id DESC"
            params = (str(group_id),)
            if not keyword:
                sql += " LIMIT ?"
                params += (int(limit),)
            rows = conn.execute(sql, params)
            result = []
            for row in rows:
                if matcher.matches(dict(row), include_owner=True):
                    result.append(self._memory_row(row, snapshot))
                    if len(result) >= limit:
                        break
            return result

    def _memory_row(self, row, snapshot):
        item = project(row, snapshot)
        item["tags"] = self._safe_load_tags(item.pop("tags_json"))
        return item

    def search_memories(self, group_id, *, user_id, query, limit, scope=None):
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        snapshot = self.identity_repository.snapshot(group_id)
        tokens = _build_query_tokens(query)
        matchers = [RecordQuery(value, snapshot) for value in dict.fromkeys([query, *tokens])]
        with self._connect() as conn:
            clause = "scope='user' AND user_id=?" if scope == "user" else "scope='group' OR (scope='user' AND user_id=?)"
            rows = conn.execute(
                f"SELECT * FROM memories WHERE group_id=? AND ({clause}) ORDER BY confidence DESC, id DESC",
                (str(group_id), None if user_id is None else str(user_id)),
            )
            result = []
            for row in rows:
                if not tokens or any(matcher.matches(dict(row), True) for matcher in matchers):
                    result.append(self._memory_row(row, snapshot))
                    if len(result) >= limit:
                        break
            return result

    def delete_memories(self, group_id, keyword):
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        snapshot = self.identity_repository.snapshot(group_id)
        candidates = snapshot.candidates(keyword)
        if snapshot.ambiguous(candidates):
            choices = "、".join(f"{snapshot.name(qq)}（{qq}）" for qq in sorted(candidates))
            raise ValueError(f"成员存在歧义：{choices}。请使用 QQ 或 #编号")
        with self._connect() as conn:
            if keyword.startswith("#") and keyword[1:].isdigit():
                return conn.execute("DELETE FROM memories WHERE group_id=? AND id=?", (str(group_id), int(keyword[1:]))).rowcount
            matcher = RecordQuery(keyword, snapshot)
            rows = conn.execute("SELECT * FROM memories WHERE group_id=?", (str(group_id),))
            ids = [row["id"] for row in rows if matcher.matches(dict(row), True)]
            conn.executemany("DELETE FROM memories WHERE id=?", [(i,) for i in ids])
            return len(ids)

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
