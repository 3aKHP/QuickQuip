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
        self._retry_init_after: float = 0.0
        self._dropped_since_unavailable = 0
        try:
            self._init_db()
        except sqlite3.Error as exc:
            logger.error("ChatArchive 数据库初始化失败 (%s)：%s", self.db_path, exc)
            self._unavailable = True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        # synchronous 是每连接设置：必须在 _connect 里设，否则热路径每条
        # 消息都以缺省 FULL 同步提交（WAL 下每次 commit fsync + 关连接
        # checkpoint，实测毫秒级且阻塞事件循环）。busy_timeout 显式对齐
        # sqlite3 缺省 5s，供 backfill/巡检并发写时明确等待上限。
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _maybe_retry_init(self) -> None:
        """启动瞬间的初始化失败不做进程级永磁：按冷却惰性重试自愈。"""
        if not self._unavailable:
            return
        now = time.monotonic()
        if now < self._retry_init_after:
            return
        self._retry_init_after = now + 60.0
        try:
            self._init_db()
        except sqlite3.Error:
            return
        logger.info("ChatArchive 数据库恢复可用（此前静默丢弃 %d 条消息）",
                    self._dropped_since_unavailable)
        self._unavailable = False
        self._dropped_since_unavailable = 0

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
        occurrence: int = 0,
    ) -> bool:
        """Append one message; duplicates (by message_id or content hash) are ignored.

        Returns True when a new row was actually inserted. ``occurrence`` 供
        回灌等无 message_id 的来源区分同秒同人同文的**不同**消息（跨源按
        相同计数对齐去重）；运行时路径不传（OneBot 群消息总带 message_id）。
        撞键时只在原行缺 user_id 且新行携带时回填该字段，不覆盖已存内容。
        """
        if not str(text).strip():
            return False
        if self._unavailable:
            self._dropped_since_unavailable += 1
            self._maybe_retry_init()
            if self._unavailable:
                return False
        gid = _safe_group_id(group_id)
        ts_val = ts if ts is not None else time()
        urls = [str(u) for u in (image_urls or []) if str(u).strip()]
        mid = str(message_id).strip() if message_id is not None else ""
        uid = str(user_id) if user_id is not None else None
        if mid:
            dedupe_key = f"m:{gid}:{mid}"
        else:
            digest = hashlib.sha1(
                f"{gid}|{int(ts_val)}|{sender_name}|{text}".encode("utf-8")
            ).hexdigest()
            dedupe_key = f"h:{digest}" if occurrence <= 0 else f"h:{digest}:{occurrence}"
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
                        uid,
                        sender_name,
                        mid or None,
                        text,
                        len(urls),
                        json.dumps(urls, ensure_ascii=False) if urls else None,
                        dedupe_key,
                        datetime.now(tz=timezone.utc).isoformat(),
                    ),
                )
                inserted = cursor.rowcount > 0
                if not inserted and uid is not None:
                    # 双采集源回灌：先入库的 wordcloud 行缺 user_id，daily 行
                    # 撞键时补齐归因字段。
                    conn.execute(
                        "UPDATE archive_messages SET user_id = ? WHERE dedupe_key = ?"
                        " AND user_id IS NULL",
                        (uid, dedupe_key),
                    )
                conn.commit()
                return inserted
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

    def list_groups(self) -> list[dict]:
        """按群聚合归档概览（Web Admin 词云群列表等）：天数近似为消息数。"""
        if self._unavailable:
            return []
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT group_id,
                       COUNT(*) AS days,
                       SUM(LENGTH(text) + 64) AS total_bytes,
                       MAX(ts) AS latest_ts
                FROM archive_messages
                GROUP BY group_id
                """
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error:
            logger.warning("chat_archive: could not list groups")
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
