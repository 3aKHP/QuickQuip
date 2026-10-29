"""MemoryStoreMixin：长期记忆的增删改查 + 分词搜索。"""

from __future__ import annotations

import json

from quickquip.common.record_content import plain, project, render, validate
from quickquip.common.record_storage import save_parts
from quickquip.common.record_search import RecordQuery

from quickquip.llm.store_parts._base import _utc_now
from quickquip.llm.memory_content import metadata, rank


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
        title: str | None = None,
        description: str | None = None,
        source_role: str = "unknown",
        max_items: int = 1000,
        source_user_id: str | None = None,
        source_message_id: str | None = None,
        writer: str = "command",
    ) -> int:
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        body = validate(content_parts) if content_parts is not None else plain(content)
        if content_parts is not None:
            content = render(body)
        if scope != "group":
            raise ValueError("记忆按群或私聊保存，不支持成员限定范围")
        title, description = metadata(content, title, description)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            count = conn.execute("SELECT count(*) FROM memories WHERE group_id=?",
                                 (str(group_id),)).fetchone()[0]
            if count >= max_items:
                raise ValueError(f"记忆容量已满：{count}/{max_items}，请覆写或删除已有条目")
            cursor = conn.execute(
                "\n"
                "                INSERT INTO memories (group_id, user_id, scope, content, "
                "tags_json, source, confidence, created_at, updated_at)\n"
                "                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)\n"
                "                ",
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
            conn.execute("UPDATE memories SET title=?, description=?, source_role=?, "
                         "source_user_id=?, "
                         "source_message_id=?, writer=? WHERE id=?",
                         (title, description, source_role, source_user_id, source_message_id,
                          writer, cursor.lastrowid))
            save_parts(conn, "memories", int(cursor.lastrowid), group_id, body)
            return int(cursor.lastrowid)

    def list_memories(
        self,
        group_id: int | str,
        *,
        limit: int | None = 10,
        keyword: str | None = None,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        if limit is not None and limit <= 0:
            return []
        snapshot = self.identity_repository.snapshot(group_id)
        matcher = RecordQuery(keyword, snapshot)
        with self._connect() as conn:
            sql = "SELECT * FROM memories WHERE group_id=? ORDER BY id DESC"
            params = (str(group_id),)
            if not keyword:
                sql += " LIMIT ? OFFSET ?"
                params += (-1 if limit is None else int(limit), int(offset))
            rows = conn.execute(sql, params)
            result = []
            for row in rows:
                if (matcher.matches(dict(row), include_owner=True)
                        or (keyword and keyword.casefold() in
                            (row["title"] + " " + row["description"]).casefold())):
                    if keyword and offset > 0:
                        offset -= 1
                        continue
                    result.append(self._memory_row(row, snapshot))
                    if limit is not None and len(result) >= limit:
                        break
            return result

    def _memory_row(self, row, snapshot):
        item = project(row, snapshot)
        item["tags"] = self._safe_load_tags(item.pop("tags_json"))
        return item

    def read_memory(self, group_id, memory_id):
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memories WHERE group_id=? AND id=?",
                               (str(group_id), memory_id)).fetchone()
            if row is None:
                raise ValueError("记忆不存在")
            return self._memory_row(row, self.identity_repository.snapshot(group_id))

    def update_memory(self, group_id, memory_id, *, version, content=None,
                      title=None, description=None, content_parts=None, tags=None,
                      confidence=None, provenance=None):
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM memories WHERE group_id=? AND id=?",
                               (str(group_id), memory_id)).fetchone()
            if row is None or row['version'] != version:
                raise ValueError("记忆已修改或删除，请重新读取")
            changed = content is not None or content_parts is not None
            body = validate(content_parts) if content_parts is not None else None
            content = render(body) if body is not None else (
                row['content'] if content is None else content)
            title, description = metadata(
                content, title if title is not None else (None if changed else row['title']),
                description if description is not None else (
                    None if changed else row['description']),
                validate_body=changed)
            conn.execute("UPDATE memories SET content=?, title=?, description=?, "
                         "tags_json=?, confidence=?, version=version+1, updated_at=? "
                         "WHERE id=? AND group_id=?",
                         (content, title, description,
                          row['tags_json'] if tags is None else json.dumps(tags),
                          row['confidence'] if confidence is None else confidence,
                          _utc_now(), memory_id, str(group_id)))
            if provenance is not None:
                conn.execute("UPDATE memories SET source_role=?, "
                         "source_user_id=?, "
                             "source_message_id=?, writer=? WHERE id=?",
                             (provenance.get('source_role', 'unknown'),
                              provenance.get('source_user_id'), provenance.get('source_message_id'),
                              provenance['writer'], memory_id))
            if changed:
                save_parts(conn, "memories", memory_id, group_id, body or plain(content))
            result = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            return self._memory_row(result, self.identity_repository.snapshot(group_id))

    def delete_memory(self, group_id, memory_id, *, version):
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM memories WHERE group_id=? AND id=? AND version=?",
                                  (str(group_id), memory_id, version))
            if not cursor.rowcount:
                raise ValueError("记忆已修改或删除，请重新读取")
        return 1

    def search_memories(self, group_id, *, user_id=None, query, limit, scope=None):
        items = self.list_memories(group_id, limit=None)
        if not query.strip():
            return items[:limit]
        ranked = rank(items, query)
        snapshot = self.identity_repository.snapshot(group_id)
        matcher = RecordQuery(query, snapshot)
        ids = {item['id'] for item in ranked}
        ranked.extend(item for item in items if item['id'] not in ids
                      and matcher.matches(item, True))
        return ranked[:limit]

    def delete_memories(self, group_id, keyword, *, literal=False):
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        snapshot = self.identity_repository.snapshot(group_id)
        if not keyword.strip():
            raise ValueError("删除关键词不能为空；清空请使用 /forget_all")
        candidates = [] if literal else snapshot.candidates(keyword)
        if snapshot.ambiguous(candidates):
            choices = "、".join(f"{snapshot.name(qq)}（{qq}）" for qq in sorted(candidates))
            raise ValueError(f"成员存在歧义：{choices}。请使用 QQ 或 #编号")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not literal and keyword.startswith("#") and keyword[1:].isdigit():
                return conn.execute(
                    "DELETE FROM memories WHERE group_id=? AND id=?",
                    (str(group_id), int(keyword[1:])),
                ).rowcount
            matcher = RecordQuery(keyword, snapshot)
            rows = conn.execute("SELECT * FROM memories WHERE group_id=?", (str(group_id),))
            ids = [row["id"] for row in rows if (
                keyword.casefold() in row['content'].casefold() if literal
                else matcher.matches(dict(row), True))]
            conn.executemany("DELETE FROM memories WHERE id=?", [(i,) for i in ids])
            return len(ids)

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
