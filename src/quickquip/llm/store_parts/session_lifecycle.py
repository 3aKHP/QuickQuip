"""Atomic chat-session bindings, archive transitions and fenced legacy writes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from dataclasses import replace
import sqlite3

from quickquip.llm.session import (
    SessionIdentity, SessionInvalidated, SessionStoreError, SessionModelProjection,
    create_session_identity,
)
from quickquip.llm.store_parts._base import _utc_now
from quickquip.llm.agent_records import LoopStatus, TriggerKind
from quickquip.llm.store_parts.agent_records import LoopHandle


def _identity(row: sqlite3.Row) -> SessionIdentity | None:
    if row["session_id"] is None and row["session_created_at"] is None:
        return None
    if not row["session_id"] or not row["session_created_at"]:
        raise SessionStoreError("会话身份记录不完整")
    try:
        created_at = datetime.fromisoformat(row["session_created_at"])
    except ValueError as exc:
        raise SessionStoreError("会话创建时间无效") from exc
    if created_at.tzinfo is None:
        raise SessionStoreError("会话创建时间缺少时区")
    return SessionIdentity(row["session_id"], created_at)


class SessionLifecycleMixin:
    """The active binding and recoverable archive own persistent identities."""

    @contextmanager
    def _session_connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        if self._unavailable:
            raise SessionStoreError("LLM 会话存储不可用")
        conn = None
        try:
            conn = self._connect()
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if write:
                conn.commit()
        except sqlite3.Error as exc:
            if conn is not None:
                conn.rollback()
            raise SessionStoreError("LLM 会话存储操作失败") from exc
        except BaseException:
            if conn is not None:
                conn.rollback()
            raise
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _ensure_session_scope(conn: sqlite3.Connection, scope: str) -> sqlite3.Row:
        conn.execute("INSERT OR IGNORE INTO agent_scopes (scope_key) VALUES (?)", (scope,))
        return conn.execute("SELECT * FROM agent_scopes WHERE scope_key = ?", (scope,)).fetchone()

    @staticmethod
    def _bind_session(conn: sqlite3.Connection, scope: str, identity: SessionIdentity) -> None:
        conn.execute(
            "UPDATE agent_scopes SET session_id = ?, session_created_at = ? WHERE scope_key = ?",
            (identity.id, identity.created_at.isoformat(), scope),
        )

    def _ensure_chat_identity(self, conn: sqlite3.Connection, scope: str) -> SessionIdentity:
        row = self._ensure_session_scope(conn, scope)
        identity = _identity(row)
        if identity is None:
            identity = create_session_identity()
            self._bind_session(conn, scope, identity)
        return identity

    def get_or_create_chat_session(self, scope: str) -> tuple[SessionIdentity, int]:
        """Freeze the identity and write generation in the same allocation transaction."""
        with self._session_connection(write=True) as conn:
            identity = self._ensure_chat_identity(conn, scope)
            generation = self._ensure_session_scope(conn, scope)["generation"]
        return self._projectable_identity(scope, identity, int(generation)), int(generation)

    def _projectable_identity(self, scope, identity, generation):
        def persist(client: str, model: str) -> str:
            with self._session_connection(write=True) as conn:
                self._check_chat_session(conn, scope, identity, generation)
                conn.execute(
                    "INSERT OR IGNORE INTO session_client_models (session_id, client, model) "
                    "VALUES (?, ?, ?)", (identity.id, client, model),
                )
                return conn.execute(
                    "SELECT model FROM session_client_models WHERE session_id = ? AND client = ?",
                    (identity.id, client),
                ).fetchone()["model"]
        return replace(identity, projection=SessionModelProjection(persist))

    @staticmethod
    def _prune_session_models(conn: sqlite3.Connection, session_id: str | None) -> None:
        conn.execute(
            "DELETE FROM session_client_models WHERE session_id = ? "
            "AND NOT EXISTS (SELECT 1 FROM agent_scopes WHERE session_id = ?) "
            "AND NOT EXISTS (SELECT 1 FROM session_archives WHERE session_id = ?)",
            (session_id, session_id, session_id),
        )

    def get_chat_session(self, scope: str) -> SessionIdentity | None:
        with self._session_connection() as conn:
            row = conn.execute(
                "SELECT * FROM agent_scopes WHERE scope_key = ?", (scope,),
            ).fetchone()
        identity = _identity(row) if row is not None else None
        return (self._projectable_identity(scope, identity, row["generation"])
                if identity is not None else None)

    @staticmethod
    def _check_chat_session(
        conn: sqlite3.Connection, scope: str, identity: SessionIdentity, generation: int,
    ) -> None:
        row = conn.execute(
            "SELECT session_id, generation FROM agent_scopes WHERE scope_key = ?", (scope,),
        ).fetchone()
        if row is None or row["session_id"] != identity.id or row["generation"] != generation:
            raise SessionInvalidated("当前会话已清空、切换或失效")

    def assert_chat_session(
        self, scope: str, identity: SessionIdentity, generation: int,
    ) -> None:
        with self._session_connection() as conn:
            self._check_chat_session(conn, scope, identity, generation)

    def _clear_session_scope(self, conn: sqlite3.Connection, scope: str) -> int:
        old_session = self._ensure_session_scope(conn, scope)["session_id"]
        deleted = conn.execute(
            "DELETE FROM conversation_messages WHERE group_id = ?", (scope,),
        ).rowcount
        conn.execute("DELETE FROM agent_loops WHERE scope_key = ?", (scope,))
        conn.execute(
            "UPDATE agent_scopes SET session_id = NULL, session_created_at = NULL, "
            "generation = generation + 1, history_revision = history_revision + 1 "
            "WHERE scope_key = ?", (scope,),
        )
        self._prune_session_models(conn, old_session)
        return deleted

    def clear_chat_session(self, scope: str) -> int:
        with self._session_connection(write=True) as conn:
            return self._clear_session_scope(conn, scope)

    @staticmethod
    def _set_private_enabled(conn: sqlite3.Connection, scope: str, enabled: bool) -> None:
        conn.execute(
            "INSERT INTO group_settings (group_id, enabled, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(group_id) DO UPDATE SET enabled = excluded.enabled, "
            "updated_at = excluded.updated_at", (scope, int(enabled), _utc_now()),
        )

    def start_private_chat_session(self, user_id: str) -> SessionIdentity:
        scope = f"private:{user_id}"
        with self._session_connection(write=True) as conn:
            self._clear_session_scope(conn, scope)
            identity = self._ensure_chat_identity(conn, scope)
            self._set_private_enabled(conn, scope, True)
            generation = self._ensure_session_scope(conn, scope)["generation"]
        return self._projectable_identity(scope, identity, generation)

    def _move_session_history(self, conn: sqlite3.Connection, source: str, target: str) -> None:
        self._ensure_session_scope(conn, source)
        self._ensure_session_scope(conn, target)
        pending = conn.execute(
            "SELECT loop_id, scope_generation, trigger_kind FROM agent_loops "
            "WHERE scope_key = ? AND closed_at IS NULL", (source,),
        ).fetchall()
        for loop in pending:
            handle = LoopHandle(
                loop_id=loop["loop_id"], scope_key=source,
                scope_generation=loop["scope_generation"],
                trigger_kind=TriggerKind(loop["trigger_kind"]),
            )
            self._close_loop_in_transaction(
                conn, handle, LoopStatus.INTERRUPTED, "session_transition",
            )
        conn.execute("UPDATE agent_loops SET scope_key = ? WHERE scope_key = ?", (target, source))
        conn.execute(
            "UPDATE conversation_messages SET group_id = ? WHERE group_id = ?", (target, source),
        )
        for scope in (source, target):
            conn.execute(
                "UPDATE agent_scopes SET generation = generation + 1, "
                "history_revision = history_revision + 1 WHERE scope_key = ?", (scope,),
            )

    def end_private_chat_session(
        self, user_id: str, *, save: bool, persona_id: str | None, preset: str,
    ) -> dict:
        scope = f"private:{user_id}"
        with self._session_connection(write=True) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM conversation_messages WHERE group_id = ?", (scope,),
            ).fetchone()[0]
            number = None
            if save and count:
                identity = self._ensure_chat_identity(conn, scope)
                number = conn.execute(
                    "SELECT COALESCE(MAX(archive_number), 0) + 1 FROM session_archives "
                    "WHERE user_id = ?", (user_id,),
                ).fetchone()[0]
                earliest = conn.execute(
                    "SELECT MIN(created_at) FROM conversation_messages WHERE group_id = ?",
                    (scope,),
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO session_archives (user_id, archive_number, persona_id, preset, "
                    "message_count, created_at, ended_at, session_id, session_created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (user_id, number, persona_id, preset or None, count, earliest or _utc_now(),
                     _utc_now(), identity.id, identity.created_at.isoformat()),
                )
                self._move_session_history(conn, scope, f"archive:{user_id}:{number}")
                conn.execute(
                    "UPDATE agent_scopes SET session_id = NULL, session_created_at = NULL "
                    "WHERE scope_key = ?", (scope,),
                )
            else:
                self._clear_session_scope(conn, scope)
            self._set_private_enabled(conn, scope, False)
        return {"deleted": int(count), "archive_number": number}

    def resume_private_chat_session(self, user_id: str, number: int | None) -> dict:
        scope = f"private:{user_id}"
        with self._session_connection(write=True) as conn:
            if number is None:
                number = conn.execute(
                    "SELECT MAX(archive_number) FROM session_archives WHERE user_id = ?",
                    (user_id,),
                ).fetchone()[0]
                if number is None:
                    return {"error": "没有可恢复的存档"}
            archive = conn.execute(
                "SELECT * FROM session_archives WHERE user_id = ? AND archive_number = ?",
                (user_id, number),
            ).fetchone()
            if archive is None:
                return {"error": f"存档 #{number} 不存在"}
            identity = _identity(archive) or create_session_identity()
            self._clear_session_scope(conn, scope)
            self._move_session_history(conn, f"archive:{user_id}:{number}", scope)
            self._bind_session(conn, scope, identity)
            self._set_private_enabled(conn, scope, True)
            conn.execute("DELETE FROM session_archives WHERE id = ?", (archive["id"],))
        return {
            "archive_number": number, "message_count": archive["message_count"],
            "preset": archive["preset"] or "", "persona_id": archive["persona_id"] or "",
        }

    def delete_archived_chat_session(self, user_id: str, number: int) -> bool:
        with self._session_connection(write=True) as conn:
            present = conn.execute(
                "SELECT id, session_id FROM session_archives "
                "WHERE user_id = ? AND archive_number = ?",
                (user_id, number),
            ).fetchone()
            if present is None:
                return False
            self._clear_session_scope(conn, f"archive:{user_id}:{number}")
            conn.execute("DELETE FROM session_archives WHERE id = ?", (present["id"],))
            self._prune_session_models(conn, present["session_id"])
        return True

    def append_session_reply(
        self, scope: str, identity: SessionIdentity, generation: int,
        *, user_message: dict | None, assistant_text: str | None,
        floor_id: int | None = None, keep_last: int | None = None,
    ) -> None:
        """Commit the legacy reply atomically under the captured session fence."""
        with self._session_connection(write=True) as conn:
            self._check_chat_session(conn, scope, identity, generation)
            if user_message is not None:
                conn.execute(
                    "INSERT INTO conversation_messages (group_id, user_id, sender_name, "
                    "canonical_name, role, content, created_at, message_id, raw_content) "
                    "VALUES (?, ?, ?, ?, 'user', ?, ?, ?, ?)",
                    (scope, str(user_message["user_id"]), user_message["sender_name"],
                     user_message["canonical_name"], user_message["content"], _utc_now(),
                     user_message["message_id"], user_message["raw_content"]),
                )
            if assistant_text is not None:
                conn.execute(
                    "INSERT INTO conversation_messages (group_id, role, content, created_at) "
                    "VALUES (?, 'assistant', ?, ?)", (scope, assistant_text, _utc_now()),
                )
            if keep_last is not None:
                conn.execute(
                    "DELETE FROM conversation_messages WHERE group_id = ? AND (id < ? OR "
                    "id NOT IN (SELECT id FROM conversation_messages WHERE group_id = ? "
                    "ORDER BY id DESC LIMIT ?))", (scope, int(floor_id or 0), scope, keep_last),
                )
