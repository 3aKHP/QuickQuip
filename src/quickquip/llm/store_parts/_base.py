"""LLMStore 基础设施：模块级工具函数 + _StoreBase（连接/schema/守卫）。

各域 mixin（ConversationStoreMixin 等）依赖 _StoreBase 提供的：
- ``self._connect()``：获取 sqlite3 连接
- ``self._unavailable``：数据库不可用守卫（各 mixin 方法开头检查）
- ``self._safe_load_tags()``：tags_json 反序列化
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


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


class _StoreBase:
    """LLMStore 的基础设施层：连接管理、schema 初始化、不可用守卫。

    各域 mixin 通过 ``self._connect()`` / ``self._unavailable`` / ``self._safe_load_tags()``
    访问这些能力，MRO 中 _StoreBase 必须排在域 mixin 之前。
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._unavailable = False
        try:
            self._ensure_schema()
            self._ensure_agent_schema()
        except sqlite3.Error as exc:
            logger.error("LLMStore 数据库初始化失败 (%s)：%s", self.path, exc)
            self._unavailable = True

    @staticmethod
    def _safe_load_tags(tags_json: str | None) -> list[str]:
        if not tags_json:
            return []
        try:
            tags = json.loads(tags_json)
            if isinstance(tags, list):
                return tags
            return []
        except json.JSONDecodeError:
            logger.warning("记忆库中存在损坏的 tags_json，已回退为空列表")
            return []

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        # agent 领域侧表使用 FK 级联（§4.2）；所有领域连接统一开启，
        # 不依赖某个连接碰巧启用。
        conn.execute("PRAGMA foreign_keys=ON")
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
