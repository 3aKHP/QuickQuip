"""群聊归档的同群只读查询服务（#72 实施计划 §5）。

定位：``ChatArchive`` 之上的查询层——有界关键词扫描、锚点/区间阅读、
覆盖信息、持久来源引用（``message_ref``）与请求级游标。框架无关，
不依赖 NoneBot / LLM 模块；由上层（llm/history_tools 等）注入群号并
渲染结果。

查询契约：
- 群/时间/已解析成员/keyset 过滤全部在 SQL 侧完成，禁止整群载入
  Python；每批 ``BATCH_ROWS`` 行，单次调用链扫描受 ``SCAN_ROW_CAP``
  与 ``QUERY_DEADLINE_S``（VM progress handler）双帽约束。
- 搜索按 ``(ts, id)`` keyset 由新到旧；命中页帽即止，扫描帽/时限触顶
  而候选未尽时返回 ``partial``（如实报告已扫行数），不得谎称全库无结果。
- 词项匹配 = 变体集合（原词 + ``casefold`` 形态）的任一子串命中；
  SQL ``LIKE`` 预筛与 Python 判定使用同一变体集（预筛是精确超集，
  不引入假阴性；``LIKE`` 通配符转义）。不接受正则。
- ``message_ref``（``hr1.<uuid8>.<row_id>``）是版本化归档定位，不含
  正文、不是授权凭证；解析后仍按当前群查询，跨群/库替换统一无效。
- 游标是 ``HistorySession`` 内的随机句柄，随请求上下文存亡；状态记录
  筛选条件、快照、位置、方向与片段偏移，续页不可改条件、不可跨群。
- 撤回旁表在 SQL 侧屏蔽（无 message_id 的旧回灌行无法关联撤回，属
  已知限制，由覆盖信息如实呈现）；交付前可再调 ``recalled_row_ids``
  重查所引用消息的撤回状态。
"""
from __future__ import annotations

import logging
import secrets
import sqlite3
import threading
from dataclasses import dataclass, field, replace
from enum import Enum
from time import monotonic
from typing import Any

from quickquip.chat.archive import ChatArchive

logger = logging.getLogger(__name__)

BATCH_ROWS = 256
"""单批扫描行数（实施计划 §5.2 建议 256）。"""

SCAN_ROW_CAP = 5000
"""单次查询调用链的候选扫描行帽；触顶返回 partial + 续页游标。"""

QUERY_DEADLINE_S = 2.0
"""单次 SQL 调用链的时限（progress handler 中止，触顶返回 partial）。"""

MAX_TERMS = 5
"""单次搜索的显式词项上限。"""

MIN_FRAGMENT_CHARS = 60
"""超长正文切片段时，剩余预算至少要能放下这段长度才切，否则整条顺延。"""

_KEY = tuple[float, int]
"""keyset 位置：(ts, row_id)。"""


def _normalize_group(group_id: int | str) -> str:
    """与归档写入侧同一防御：仅接受纯数字群号。"""
    s = str(group_id).strip()
    if not s.isdigit():
        raise ValueError(f"Invalid group_id (must be all digits): {group_id!r}")
    return s


def _like_escape(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _ascii_lower(s: str) -> str:
    """与 SQLite ``LIKE`` 一致的 ASCII 折叠（仅 A-Z 小写化，其余原样）。

    Python 判定必须与 ``LIKE`` 折叠口径相同，否则预筛命中的行会在精化
    时被误丢（假阴性），或反之产生两套口径的不一致命中。
    """
    return "".join(c.lower() if "A" <= c <= "Z" else c for c in s)


def _term_variants(term: str) -> list[str]:
    """匹配变体：原词 + casefold 形态（去重、去空）。

    SQL ``LIKE`` 与 Python 判定共用同一变体集：``LIKE`` 默认仅对 ASCII
    大小写不敏感，casefold 变体补上非 ASCII 字母的小写形态；两套判定
    语义完全一致，预筛不会漏掉 Python 侧会命中的行。
    """
    variants: list[str] = []
    for value in (term, term.casefold()):
        if value and value not in variants:
            variants.append(value)
    return variants


class QueryStatus(str, Enum):
    """查询结果状态（实施计划 §5.4）。partial 不得包装成 empty。"""

    OK = "ok"
    EMPTY = "empty"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    INVALID_REQUEST = "invalid_request"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass(frozen=True)
class ArchivedMessage:
    """查询侧消息形态：含归档行 ID（来源引用/锚点的定位基础）。"""

    row_id: int
    ts: float
    user_id: str | None
    sender_name: str
    text: str
    image_count: int
    message_id: str | None


@dataclass(frozen=True)
class CoverageInfo:
    """归档覆盖事实。跨度只证明已存记录范围；停机/重启间隙无法回填，
    连续覆盖未知是固定标注，不因查询成功而消失。"""

    earliest_ts: float | None
    latest_ts: float | None
    total_messages: int
    continuous_coverage_unknown: bool = True


@dataclass
class SearchOutcome:
    status: QueryStatus
    hits: list[ArchivedMessage] = field(default_factory=list)  # 新→旧
    scanned_rows: int = 0
    has_more: bool = False
    stop_reason: str | None = None  # "scan_cap" | "deadline" | "page_cap"
    cursor_token: str | None = None
    coverage: CoverageInfo | None = None
    detail: str = ""


@dataclass
class ReadOutcome:
    status: QueryStatus
    messages: list[ArchivedMessage] = field(default_factory=list)  # 升序
    # 最后一条为片段时的描述：(row_id, 本次片段起点, 全文长度)
    fragment: tuple[int, int, int] | None = None
    older_cursor: str | None = None  # 向更早方向续读
    newer_cursor: str | None = None  # 向更新方向续读
    stop_reason: str | None = None  # "message_cap" | "char_cap" | "window_end"
    coverage: CoverageInfo | None = None
    detail: str = ""


class HistorySession:
    """请求级游标命名空间：随调用方请求上下文（如 ToolExecutionContext）
    创建与销毁，实现"游标只在当前检索会话内有效"。

    游标句柄为本会话内随机串；状态自带 group_id，跨群解析一律拒绝。
    数量帽 FIFO 淘汰，防止模型循环索要游标撑爆内存。
    """

    MAX_CURSORS = 32

    def __init__(self) -> None:
        self._cursors: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def issue(self, state: dict[str, Any]) -> str:
        token = secrets.token_urlsafe(9)
        with self._lock:
            while len(self._cursors) >= self.MAX_CURSORS:
                self._cursors.pop(next(iter(self._cursors)))
            self._cursors[token] = state
        return token

    def resolve(self, token: str, group_id: str) -> dict[str, Any] | None:
        """解析游标；不存在或跨群均返回 None（不区分，避免泄露他群状态）。"""
        with self._lock:
            state = self._cursors.get(str(token).strip())
        if state is None or state.get("group_id") != group_id:
            return None
        return state


class HistoryQueryService:
    """同群只读查询门面。持有 ``ChatArchive`` 引用；线程安全（每次调用
    独立连接 + 游标锁），供 asyncio.to_thread 调用。"""

    REF_PREFIX = "hr1"

    def __init__(
        self,
        archive: ChatArchive,
        *,
        batch_rows: int = BATCH_ROWS,
        scan_row_cap: int = SCAN_ROW_CAP,
        query_deadline_s: float = QUERY_DEADLINE_S,
    ) -> None:
        self.archive = archive
        self.batch_rows = batch_rows
        self.scan_row_cap = scan_row_cap
        self.query_deadline_s = query_deadline_s

    # ------------------------------------------------------------------
    # 来源引用（message_ref）
    # ------------------------------------------------------------------

    def encode_ref(self, row_id: int) -> str:
        """``hr1.<uuid前8>.<行ID>``；归档 UUID 不可用时用 ``x`` 占位，
        解码侧按库替换处理（无效引用）。"""
        prefix = self.archive.archive_uuid[:8] if self.archive.archive_uuid else "x"
        return f"{self.REF_PREFIX}.{prefix}.{int(row_id)}"

    def decode_ref(self, ref: str) -> int | None:
        """解析引用为归档行 ID；格式错、版本不符或库已替换返回 None。"""
        parts = str(ref).strip().split(".")
        if len(parts) != 3 or parts[0] != self.REF_PREFIX:
            return None
        _, uuid_prefix, row_digits = parts
        if not row_digits.isdigit():
            return None
        if not self.archive.archive_uuid or not self.archive.archive_uuid.startswith(
            uuid_prefix
        ):
            return None
        row_id = int(row_digits)
        return row_id if row_id > 0 else None

    # ------------------------------------------------------------------
    # 覆盖与撤回
    # ------------------------------------------------------------------

    def coverage(self, group_id: int | str) -> CoverageInfo | None:
        """该群归档覆盖事实；库不可用返回 None（调用方按降级呈现）。"""
        gid = self._try_group(group_id)
        if gid is None:
            return None
        conn = self.archive.query_connection()
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS c, MIN(ts) AS a, MAX(ts) AS b"
                " FROM archive_messages WHERE group_id = ?",
                (gid,),
            ).fetchone()
            if row is None:
                return CoverageInfo(None, None, 0)
            return CoverageInfo(row["a"], row["b"], row["c"])
        except sqlite3.Error:
            return None
        finally:
            conn.close()

    def recalled_row_ids(self, group_id: int | str, row_ids: list[int]) -> set[int]:
        """交付前重查：按行 ID 集合返回其中已撤回的行（报告引用复查用）。"""
        if not row_ids:
            return set()
        gid = self._try_group(group_id)
        if gid is None:
            return set()
        conn = self.archive.query_connection()
        if conn is None:
            return set()
        try:
            placeholders = ",".join("?" for _ in row_ids)
            rows = conn.execute(
                f"""
                SELECT m.id AS id
                FROM archive_messages m
                JOIN recalled_messages r
                  ON r.group_id = m.group_id AND r.message_id = m.message_id
                WHERE m.group_id = ? AND m.id IN ({placeholders})
                """,
                (gid, *row_ids),
            ).fetchall()
            return {int(r["id"]) for r in rows}
        except sqlite3.Error:
            return set()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------

    def search(
        self,
        group_id: int | str,
        session: HistorySession,
        *,
        terms: list[str],
        start_ts: float,
        end_ts: float,
        speaker_user_ids: list[str] | None = None,
        max_hits: int = 5,
    ) -> SearchOutcome:
        """按词项搜索当前群归档窗口（新→旧）。新搜索必须有非空 terms；
        续页走 ``search_continue``。"""
        gid = self._try_group(group_id)
        if gid is None:
            return SearchOutcome(status=QueryStatus.INVALID_REQUEST, detail="bad_group")
        clean_terms = [str(t).strip() for t in terms if str(t).strip()]
        if not clean_terms:
            return SearchOutcome(status=QueryStatus.INVALID_REQUEST, detail="empty_terms")
        if len(clean_terms) > MAX_TERMS:
            return SearchOutcome(status=QueryStatus.INVALID_REQUEST, detail="too_many_terms")
        if end_ts <= start_ts:
            return SearchOutcome(status=QueryStatus.INVALID_REQUEST, detail="bad_window")
        snapshot = self._current_snapshot()
        if snapshot is None:
            return SearchOutcome(
                status=QueryStatus.UNAVAILABLE, detail="archive_unavailable"
            )
        state: dict[str, Any] = {
            "kind": "search",
            "group_id": gid,
            "terms": clean_terms,
            "start": float(start_ts),
            "end": float(end_ts),
            "speaker_ids": [str(u) for u in (speaker_user_ids or [])],
            "snapshot_max_id": snapshot,
            "last_key": None,
            "max_hits": int(max_hits),
        }
        return self._run_search(session, state)

    def search_continue(
        self, group_id: int | str, session: HistorySession, *, cursor_token: str
    ) -> SearchOutcome:
        """续页：条件/快照来自游标状态，不可修改。"""
        gid = self._try_group(group_id)
        if gid is None:
            return SearchOutcome(status=QueryStatus.INVALID_REQUEST, detail="bad_group")
        state = session.resolve(cursor_token, gid)
        if state is None or state.get("kind") != "search":
            return SearchOutcome(status=QueryStatus.INVALID_REQUEST, detail="bad_cursor")
        return self._run_search(session, state)

    def _run_search(self, session: HistorySession, state: dict[str, Any]) -> SearchOutcome:
        gid: str = state["group_id"]
        terms: list[str] = state["terms"]
        max_hits: int = max(1, int(state.get("max_hits", 5)))
        flat_variants = [v for t in terms for v in _term_variants(t)]
        like_clauses = " OR ".join("m.text LIKE ? ESCAPE '\\'" for _ in flat_variants)
        like_params = [f"%{_like_escape(v)}%" for v in flat_variants]
        speaker_ids: list[str] = [u for u in (state.get("speaker_ids") or []) if u]
        speaker_clause = ""
        if speaker_ids:
            speaker_clause = (
                " AND m.user_id IN (" + ",".join("?" for _ in speaker_ids) + ")"
            )

        deadline_at = monotonic() + self.query_deadline_s
        deadline_hit = threading.Event()
        scanned = 0
        hits: list[ArchivedMessage] = []
        stop_reason: str | None = None
        exhausted = False
        last_key: _KEY | None = state.get("last_key")

        conn = self.archive.query_connection()
        if conn is None:
            return SearchOutcome(
                status=QueryStatus.UNAVAILABLE,
                coverage=self.coverage(gid),
                detail="archive_unavailable",
            )

        def _guard() -> int:
            if monotonic() > deadline_at:
                deadline_hit.set()
                return 1
            return 0

        try:
            conn.set_progress_handler(_guard, 2000)
            while True:
                keyset_clause = ""
                keyset_params: list[Any] = []
                if last_key is not None:
                    keyset_clause = " AND (m.ts < ? OR (m.ts = ? AND m.id < ?))"
                    keyset_params = [last_key[0], last_key[0], last_key[1]]
                rows = conn.execute(
                    f"""
                    SELECT m.id, m.ts, m.user_id, m.sender_name, m.text,
                           m.image_count, m.message_id
                    FROM archive_messages m
                    WHERE m.group_id = ?
                      AND m.ts >= ? AND m.ts < ?
                      AND m.id <= ?
                      AND NOT EXISTS (
                          SELECT 1 FROM recalled_messages r
                          WHERE r.group_id = m.group_id
                            AND r.message_id = m.message_id
                      ){speaker_clause}{keyset_clause}
                      AND ({like_clauses})
                    ORDER BY m.ts DESC, m.id DESC
                    LIMIT ?
                    """,
                    (
                        gid,
                        state["start"],
                        state["end"],
                        state["snapshot_max_id"],
                        *speaker_ids,
                        *keyset_params,
                        *like_params,
                        self.batch_rows,
                    ),
                ).fetchall()
                scanned += len(rows)
                for row in rows:
                    if self._row_matches(row["text"], flat_variants):
                        hits.append(self._row_to_message(row))
                        if len(hits) >= max_hits:
                            break
                if len(hits) >= max_hits:
                    last_hit = hits[-1]
                    state["last_key"] = [last_hit.ts, last_hit.row_id]
                    stop_reason = "page_cap"
                    break
                if len(rows) < self.batch_rows:
                    exhausted = True
                    break
                tail_key: _KEY = (float(rows[-1]["ts"]), int(rows[-1]["id"]))
                state["last_key"] = [tail_key[0], tail_key[1]]
                last_key = tail_key
                if scanned >= self.scan_row_cap:
                    stop_reason = "scan_cap"
                    break
        except sqlite3.OperationalError:
            if deadline_hit.is_set():
                # 本批未交付：续页从上一个已交付边界（或窗口起点）继续
                stop_reason = "deadline"
            else:
                return SearchOutcome(
                    status=QueryStatus.UNAVAILABLE,
                    coverage=self.coverage(gid),
                    detail="database_busy",
                )
        except sqlite3.Error:
            return SearchOutcome(
                status=QueryStatus.UNAVAILABLE,
                coverage=self.coverage(gid),
                detail="database_error",
            )
        finally:
            conn.set_progress_handler(None, 0)
            conn.close()

        has_more = not exhausted
        cursor_token = session.issue(state) if has_more else None
        status = (
            QueryStatus.OK
            if hits
            else (QueryStatus.EMPTY if exhausted else QueryStatus.PARTIAL)
        )
        return SearchOutcome(
            status=status,
            hits=hits,
            scanned_rows=scanned,
            has_more=has_more,
            stop_reason=stop_reason,
            cursor_token=cursor_token,
            coverage=self.coverage(gid),
        )

    @staticmethod
    def _row_matches(text: str, flat_variants: list[str]) -> bool:
        """Python 判定与 SQL LIKE 预筛同口径：变体子串命中（ASCII 折叠）。"""
        haystack = _ascii_lower(text)
        return any(_ascii_lower(v) in haystack for v in flat_variants)

    # ------------------------------------------------------------------
    # 阅读
    # ------------------------------------------------------------------

    def read_anchor(
        self,
        group_id: int | str,
        session: HistorySession,
        *,
        ref: str,
        direction: str = "around",
        radius: int = 5,
        max_messages: int = 12,
        max_chars: int = 1600,
    ) -> ReadOutcome:
        """按来源引用展开命中附近消息。direction ∈ around|before|after。"""
        gid = self._try_group(group_id)
        if gid is None:
            return ReadOutcome(status=QueryStatus.INVALID_REQUEST, detail="bad_group")
        if direction not in ("around", "before", "after"):
            return ReadOutcome(status=QueryStatus.INVALID_REQUEST, detail="bad_direction")
        row_id = self.decode_ref(ref)
        if row_id is None:
            return ReadOutcome(status=QueryStatus.INVALID_REQUEST, detail="bad_ref")
        snapshot = self._current_snapshot()
        if snapshot is None:
            return ReadOutcome(status=QueryStatus.UNAVAILABLE, detail="archive_unavailable")
        anchor = self._fetch_row(gid, row_id, snapshot)
        if anchor is None:
            # 不存在、跨群、已撤回统一拒绝，不区分原因（不泄露他群记录）
            return ReadOutcome(
                status=QueryStatus.INVALID_REQUEST, detail="anchor_unavailable"
            )
        key = (anchor.ts, anchor.row_id)
        want_before = radius if direction in ("around", "before") else 0
        want_after = radius if direction in ("around", "after") else 0
        # 单侧需求为 0 时不探测（limit=1 的探针会把仅剩一条误报为"还有更多"）
        if want_before > 0:
            older, older_more = self._fetch_side(
                gid, snapshot, key, "older", want_before + 1
            )
        else:
            older, older_more = [], True
        if want_after > 0:
            newer, newer_more = self._fetch_side(
                gid, snapshot, key, "newer", want_after + 1
            )
        else:
            newer, newer_more = [], True
        if older_more:
            older = older[:-1]
        if newer_more:
            newer = newer[:-1]
        sequence = list(reversed(older)) + [anchor] + newer
        return self._assemble_read(
            session, gid, snapshot, sequence,
            older_exhausted=not older_more,
            newer_exhausted=not newer_more,
            max_messages=max_messages,
            max_chars=max_chars,
        )

    def read_range(
        self,
        group_id: int | str,
        session: HistorySession,
        *,
        start_ts: float,
        end_ts: float,
        max_messages: int = 12,
        max_chars: int = 1600,
    ) -> ReadOutcome:
        """按时间区间升序阅读（从区间起点开始）。"""
        gid = self._try_group(group_id)
        if gid is None:
            return ReadOutcome(status=QueryStatus.INVALID_REQUEST, detail="bad_group")
        if end_ts <= start_ts:
            return ReadOutcome(status=QueryStatus.INVALID_REQUEST, detail="bad_window")
        snapshot = self._current_snapshot()
        if snapshot is None:
            return ReadOutcome(status=QueryStatus.UNAVAILABLE, detail="archive_unavailable")
        rows = self._fetch_range(gid, snapshot, start_ts, end_ts, max_messages + 1)
        has_more = len(rows) > max_messages
        sequence = rows[:max_messages] if max_messages > 0 else []
        return self._assemble_read(
            session, gid, snapshot, sequence,
            older_exhausted=True,
            newer_exhausted=not has_more,
            max_messages=max_messages,
            max_chars=max_chars,
        )

    def read_continue(
        self, group_id: int | str, session: HistorySession, *, cursor_token: str
    ) -> ReadOutcome:
        """续读：方向/位置/片段偏移来自游标状态，不可修改。"""
        gid = self._try_group(group_id)
        if gid is None:
            return ReadOutcome(status=QueryStatus.INVALID_REQUEST, detail="bad_group")
        state = session.resolve(cursor_token, gid)
        if state is None or state.get("kind") != "read":
            return ReadOutcome(status=QueryStatus.INVALID_REQUEST, detail="bad_cursor")
        snapshot = int(state.get("snapshot_max_id") or 0) or self._current_snapshot()
        if not snapshot:
            return ReadOutcome(status=QueryStatus.UNAVAILABLE, detail="archive_unavailable")
        direction: str = state["direction"]
        max_messages = max(1, int(state.get("max_messages", 12)))
        max_chars = int(state.get("max_chars", 1600))
        resume_row_id = state.get("resume_row_id")
        char_offset = int(state.get("char_offset", 0) or 0)
        last_key = state.get("last_key")

        # 片段续读：先把该行剩余正文作为首条输出
        prefix: list[ArchivedMessage] = []
        prefix_total = 0
        if resume_row_id is not None:
            row = self._fetch_row(gid, int(resume_row_id), snapshot)
            if row is not None:
                prefix_total = len(row.text)
                prefix = [
                    ArchivedMessage(
                        row_id=row.row_id,
                        ts=row.ts,
                        user_id=row.user_id,
                        sender_name=row.sender_name,
                        text=row.text[char_offset:],
                        image_count=row.image_count,
                        message_id=row.message_id,
                    )
                ]
        # keyset 锚点：优先取游标记录的 (ts, id)，取不到行也能继续翻页
        key: _KEY | None = None
        if last_key is not None:
            key = (float(last_key[0]), int(last_key[1]))
        elif prefix:
            key = (prefix[0].ts, prefix[0].row_id)
        if key is None:
            return ReadOutcome(status=QueryStatus.INVALID_REQUEST, detail="bad_cursor")

        if direction == "newer":
            rows, more = self._fetch_side(gid, snapshot, key, "newer", max_messages + 1)
            if more:
                rows = rows[:-1]
            sequence = prefix + rows
        else:
            rows, more = self._fetch_side(gid, snapshot, key, "older", max_messages + 1)
            if more:
                rows = rows[:-1]
            sequence = prefix + list(reversed(rows))
        exhausted = not more
        # 续页方向由游标固定：反向不签发回读游标（已交付内容按方向推进，
        # 模型要回读应另开锚点阅读），反向侧按"不再展开"处理
        return self._assemble_read(
            session, gid, snapshot, sequence,
            older_exhausted=(direction != "older" or exhausted),
            newer_exhausted=(direction != "newer" or exhausted),
            max_messages=max_messages,
            max_chars=max_chars,
            fragment_start=(
                (int(resume_row_id), char_offset, prefix_total)
                if resume_row_id is not None and prefix
                else None
            ),
        )

    # ------------------------------------------------------------------
    # 内部：取数与装配
    # ------------------------------------------------------------------

    @staticmethod
    def _try_group(group_id: int | str) -> str | None:
        try:
            return _normalize_group(group_id)
        except ValueError:
            return None

    def _current_snapshot(self) -> int | None:
        """当前快照上界 = 全库 MAX(id)（行 ID 全局自增，与群无关）。"""
        conn = self.archive.query_connection()
        if conn is None:
            return None
        try:
            row = conn.execute("SELECT MAX(id) AS m FROM archive_messages").fetchone()
            return int(row["m"] or 0)
        except sqlite3.Error:
            return None
        finally:
            conn.close()

    def _fetch_row(self, gid: str, row_id: int, snapshot: int) -> ArchivedMessage | None:
        conn = self.archive.query_connection()
        if conn is None:
            return None
        try:
            row = conn.execute(
                """
                SELECT m.id, m.ts, m.user_id, m.sender_name, m.text,
                       m.image_count, m.message_id
                FROM archive_messages m
                WHERE m.id = ? AND m.group_id = ? AND m.id <= ?
                  AND NOT EXISTS (
                      SELECT 1 FROM recalled_messages r
                      WHERE r.group_id = m.group_id
                        AND r.message_id = m.message_id
                  )
                """,
                (row_id, gid, snapshot),
            ).fetchone()
            return self._row_to_message(row) if row is not None else None
        except sqlite3.Error:
            return None
        finally:
            conn.close()

    def _fetch_side(
        self, gid: str, snapshot: int, key: _KEY, side: str, limit: int
    ) -> tuple[list[ArchivedMessage], bool]:
        """keyset 单侧取数（严格大于/小于 key，不含 key 行本身）。
        older 返回新→旧序（调用方自行反转）；newer 返回升序。
        返回 (消息列表, 该侧窗口是否可能还有更多)。limit 不足整批返回
        False；恰好取满视为可能还有（保守，由上层 +1 探针修正）。"""
        conn = self.archive.query_connection()
        if conn is None:
            return [], False
        if side == "older":
            clause = "(m.ts < ? OR (m.ts = ? AND m.id < ?))"
            order = "m.ts DESC, m.id DESC"
        else:
            clause = "(m.ts > ? OR (m.ts = ? AND m.id > ?))"
            order = "m.ts ASC, m.id ASC"
        try:
            rows = conn.execute(
                f"""
                SELECT m.id, m.ts, m.user_id, m.sender_name, m.text,
                       m.image_count, m.message_id
                FROM archive_messages m
                WHERE m.group_id = ?
                  AND m.id <= ?
                  AND {clause}
                  AND NOT EXISTS (
                      SELECT 1 FROM recalled_messages r
                      WHERE r.group_id = m.group_id
                        AND r.message_id = m.message_id
                  )
                ORDER BY {order}
                LIMIT ?
                """,
                (gid, snapshot, key[0], key[0], key[1], limit),
            ).fetchall()
            more = len(rows) >= limit
            return [self._row_to_message(r) for r in rows], more
        except sqlite3.Error:
            return [], False
        finally:
            conn.close()

    def _fetch_range(
        self, gid: str, snapshot: int, start_ts: float, end_ts: float, limit: int
    ) -> list[ArchivedMessage]:
        conn = self.archive.query_connection()
        if conn is None:
            return []
        try:
            rows = conn.execute(
                """
                SELECT m.id, m.ts, m.user_id, m.sender_name, m.text,
                       m.image_count, m.message_id
                FROM archive_messages m
                WHERE m.group_id = ? AND m.ts >= ? AND m.ts < ? AND m.id <= ?
                  AND NOT EXISTS (
                      SELECT 1 FROM recalled_messages r
                      WHERE r.group_id = m.group_id
                        AND r.message_id = m.message_id
                  )
                ORDER BY m.ts ASC, m.id ASC
                LIMIT ?
                """,
                (gid, start_ts, end_ts, snapshot, limit),
            ).fetchall()
            return [self._row_to_message(r) for r in rows]
        except sqlite3.Error:
            return []
        finally:
            conn.close()

    def _assemble_read(
        self,
        session: HistorySession,
        gid: str,
        snapshot: int,
        sequence: list[ArchivedMessage],
        *,
        older_exhausted: bool,
        newer_exhausted: bool,
        max_messages: int,
        max_chars: int,
        fragment_start: tuple[int, int, int] | None = None,
    ) -> ReadOutcome:
        """消息帽 + 字符帽装配（升序遍历）。

        - 超长正文切可续读片段：剩余预算 ≥ MIN_FRAGMENT_CHARS 才切，
          否则整条顺延给续页；首条保底切 MIN_FRAGMENT_CHARS 保证推进。
        - 片段只可能发生在输出末尾（最新端），older 续读永远整条开始。
        - 游标以「输出边界」签发：older 边界 = 序列最旧一条；newer 边界
          = 已交付的最末一条——片段行记录续读偏移（resume），整条顺延或
          常规截断则从最后完整交付行的下一条继续。
        """
        coverage = self.coverage(gid)
        if not sequence:
            return ReadOutcome(
                status=QueryStatus.EMPTY,
                coverage=coverage,
                stop_reason="window_end",
            )
        cap = max(1, int(max_messages))
        remaining = max(int(max_chars), 0)
        base_offset = fragment_start[1] if fragment_start is not None else 0
        messages: list[ArchivedMessage] = []
        fragment: tuple[int, int, int] | None = None
        stopped_at = len(sequence)

        for index, message in enumerate(sequence):
            if len(messages) >= cap:
                stopped_at = index
                break
            is_resume_head = fragment_start is not None and index == 0
            total_len = fragment_start[2] if is_resume_head else len(message.text)
            cut = remaining if index > 0 else max(remaining, MIN_FRAGMENT_CHARS)
            if len(message.text) <= cut:
                messages.append(message)
                remaining -= len(message.text)
                continue
            offset = base_offset if is_resume_head else 0
            messages.append(
                replace(message, text=message.text[:cut])
            )
            fragment = (message.row_id, offset, total_len)
            remaining = 0
            stopped_at = index + 1
            break

        truncated_last = fragment is not None
        leftover = len(sequence) - stopped_at
        if truncated_last:
            stop_reason = "char_cap"
        elif leftover > 0 or not (older_exhausted and newer_exhausted):
            stop_reason = "message_cap"
        else:
            stop_reason = "window_end"

        older_cursor = None
        if not older_exhausted:
            boundary = sequence[0]
            older_cursor = session.issue({
                "kind": "read",
                "group_id": gid,
                "direction": "older",
                "snapshot_max_id": snapshot,
                "last_key": [boundary.ts, boundary.row_id],
                "resume_row_id": None,
                "char_offset": 0,
                "max_messages": cap,
                "max_chars": int(max_chars),
            })
        newer_cursor = None
        # 窗口探针说"没有更多整条"时，预算截断（片段/顺延）仍意味着
        # 有未交付内容：一样必须签发续读游标
        needs_newer = (not newer_exhausted) or truncated_last or leftover > 0
        if needs_newer and messages:
            last = messages[-1]
            resume_row_id = None
            char_offset = 0
            if truncated_last:
                # 续读从片段剩余部分开始（resume 行 = 片段行本身）
                resume_row_id = fragment[0]
                char_offset = fragment[1] + len(last.text)
            newer_cursor = session.issue({
                "kind": "read",
                "group_id": gid,
                "direction": "newer",
                "snapshot_max_id": snapshot,
                "last_key": [last.ts, last.row_id],
                "resume_row_id": resume_row_id,
                "char_offset": char_offset,
                "max_messages": cap,
                "max_chars": int(max_chars),
            })
        return ReadOutcome(
            status=QueryStatus.OK,
            messages=messages,
            fragment=fragment,
            older_cursor=older_cursor,
            newer_cursor=newer_cursor,
            stop_reason=stop_reason,
            coverage=coverage,
        )

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> ArchivedMessage:
        return ArchivedMessage(
            row_id=int(row["id"]),
            ts=float(row["ts"]),
            user_id=row["user_id"],
            sender_name=row["sender_name"],
            text=row["text"],
            image_count=int(row["image_count"] or 0),
            message_id=row["message_id"],
        )
