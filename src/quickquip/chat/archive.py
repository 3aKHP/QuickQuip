"""聊天记录归档与序列化器（1.15.2 A 线）。

定位：完全忠于原文的群聊消息归档。归档一次、多处消费——日报、词云、
早午晚报、周/月报与未来的年度报告都从同一份归档读取序列化视图。

保真契约：
- 归档层只忠实存档，不做任何清洗；清洗策略属于各消费侧
  （词云剥占位/@提及、日报加时间戳与发言人前缀等）。
- 多媒体不进任何消费管线：图片仅以 URL 列表与数量留档，
  正文中的 ``[图片]`` 占位符由渲染层既有规则产生。
- 永不删除：归档不设保留期，发布成功后也不清理（年度报告取数依赖）。

去重：``dedupe_key`` 唯一——运行时写入用 ``m:<message_id>``；历史回灌
等无 message_id 的来源用内容哈希。``INSERT OR IGNORE`` 使重复写入无害。
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from time import time

from quickquip.common.paths import CHAT_ARCHIVE_DB_PATH

logger = logging.getLogger(__name__)


def _safe_group_id(group_id: int | str) -> str:
    """Filesystem-safe, digit-only group ID（对齐既有采集器防御）。"""
    s = str(group_id).strip()
    if not s.isdigit():
        raise ValueError(f"Invalid group_id (must be all digits): {group_id!r}")
    return s


class ChatArchive:
    """SQLite 聊天归档：append-only 写入，窗口/全量读取。

    热路径单条 insert（WAL + NORMAL 同步），失败只告警不阻断消息主链路
    （对齐被替换的 JSONL 采集器行为）。表结构仅 ``CREATE IF NOT EXISTS``，
    Bot 与 Web Admin 并发首启动无迁移竞态。
    """

    def __init__(self, db_path: str | Path = CHAT_ARCHIVE_DB_PATH):
        self.db_path = Path(db_path)
        self._unavailable = False
        try:
            self._init_db()
        except sqlite3.Error as exc:
            logger.error("ChatArchive 数据库初始化失败 (%s)：%s", self.db_path, exc)
            self._unavailable = True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS archive_messages (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id      TEXT NOT NULL,
                    ts            REAL NOT NULL,
                    user_id       TEXT,
                    sender_name   TEXT NOT NULL,
                    message_id    TEXT,
                    text          TEXT NOT NULL,
                    image_count   INTEGER NOT NULL DEFAULT 0,
                    image_urls    TEXT,
                    dedupe_key    TEXT NOT NULL UNIQUE,
                    created_at    TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_archive_group_ts"
                " ON archive_messages(group_id, ts)"
            )
            conn.commit()
        finally:
            conn.close()

    def record(
        self,
        group_id: int | str,
        sender_name: str,
        text: str,
        ts: float | None = None,
        user_id: int | str | None = None,
        message_id: int | str | None = None,
        image_urls: list[str] | None = None,
    ) -> bool:
        """Append one message; duplicates (by message_id or content hash) are ignored.

        Returns True when a new row was actually inserted.
        """
        if self._unavailable or not str(text).strip():
            return False
        gid = _safe_group_id(group_id)
        ts_val = ts if ts is not None else time()
        urls = [str(u) for u in (image_urls or []) if str(u).strip()]
        mid = str(message_id).strip() if message_id is not None else ""
        if mid:
            dedupe_key = f"m:{gid}:{mid}"
        else:
            digest = hashlib.sha1(
                f"{gid}|{int(ts_val)}|{sender_name}|{text}".encode("utf-8")
            ).hexdigest()
            dedupe_key = f"h:{digest}"
        try:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO archive_messages
                        (group_id, ts, user_id, sender_name, message_id, text,
                         image_count, image_urls, dedupe_key, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        gid,
                        ts_val,
                        str(user_id) if user_id is not None else None,
                        sender_name,
                        mid or None,
                        text,
                        len(urls),
                        json.dumps(urls, ensure_ascii=False) if urls else None,
                        dedupe_key,
                        datetime.now(tz=timezone.utc).isoformat(),
                    ),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()
        except sqlite3.Error:
            logger.warning("chat_archive: failed to write message for group %s", gid)
            return False

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> dict:
        """消费侧兼容形态：与被替换的 JSONL 采集器同键，另附归档扩展字段。"""
        return {
            "sender": row["sender_name"],
            "text": row["text"],
            "ts": row["ts"],
            "user_id": row["user_id"],
            "message_id": row["message_id"],
            "image_count": row["image_count"],
        }

    def read_window(self, group_id: int | str, start_ts: float, end_ts: float) -> list[dict]:
        """Return all messages in [start_ts, end_ts) sorted by timestamp."""
        if self._unavailable:
            return []
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM archive_messages
                WHERE group_id = ? AND ts >= ? AND ts < ?
                ORDER BY ts ASC, id ASC
                """,
                (_safe_group_id(group_id), start_ts, end_ts),
            ).fetchall()
            return [self._row_to_message(row) for row in rows]
        except sqlite3.Error:
            logger.warning("chat_archive: could not read window for group %s", group_id)
            return []
        finally:
            conn.close()

    def read_all(self, group_id: int | str) -> list[dict]:
        """Return all archived messages for a group sorted by timestamp."""
        if self._unavailable:
            return []
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM archive_messages WHERE group_id = ? ORDER BY ts ASC, id ASC",
                (_safe_group_id(group_id),),
            ).fetchall()
            return [self._row_to_message(row) for row in rows]
        except sqlite3.Error:
            logger.warning("chat_archive: could not read all for group %s", group_id)
            return []
        finally:
            conn.close()

    def stats(self) -> dict:
        """归档规模概览（Admin/巡检用）：总条数、群数、字节量。"""
        if self._unavailable:
            return {"available": False}
        conn = self._connect()
        try:
            total = conn.execute("SELECT COUNT(*) AS n FROM archive_messages").fetchone()["n"]
            groups = conn.execute(
                "SELECT COUNT(DISTINCT group_id) AS n FROM archive_messages"
            ).fetchone()["n"]
            return {"available": True, "messages": total, "groups": groups}
        except sqlite3.Error:
            return {"available": False}
        finally:
            conn.close()
