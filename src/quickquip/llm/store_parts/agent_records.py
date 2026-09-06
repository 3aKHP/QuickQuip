"""AgentRecordsStoreMixin：Agent Loop 执行记录领域的持久化（§4）。

三视图契约（§3.2）中的「执行记录」与「交付记录」落在本 mixin：
``agent_loops`` / ``agent_turns`` / ``agent_tool_executions`` /
``agent_deliveries`` / ``agent_delivery_attempts`` 五张侧表加
``conversation_messages`` 的 loop/turn 关联列。重放投影读取
（``load_closed_loops``）只返回完整已关闭 Loop。

写入纪律（§4.2）：

- 同一业务提交的主表行、侧表行、字节账本在一个事务内完成；Turn 写入
  与其全部工具声明、全部文字 Chunk 同事务，事务提交成功之后才允许
  发送或执行工具。
- 每次写入验证 ``scope_generation`` 与 Loop 仍可写；清空后迟到结果
  不得新建内容。
- 关键写路径用 ``BEGIN IMMEDIATE`` 取写锁后再校验，数据库
  generation/revision 是跨进程（Bot/Web）的最终写入屏障。

迁移（§4.3）：``BEGIN IMMEDIATE`` + ``agent_schema_migrations`` 版本表，
旧库按 user 行分组回填 legacy Loop/Turn/delivery；不访问网络与 QQ。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from collections import deque
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from quickquip.llm.agent_records import (
    AGENT_RECORD_VERSION,
    DeliveryKind,
    DeliveryPlanItem,
    DeliveryPolicy,
    DeliveryReceipt,
    DeliveryStatus,
    LoopStatus,
    MAX_LOOP_RECORD_BYTES,
    MAX_NATIVE_STATE_BYTES,
    MAX_PERSISTED_TOOL_ARGUMENT_BYTES,
    MAX_PERSISTED_TOOL_RESULT_BYTES,
    NativeOmissionReason,
    ResultOmissionReason,
    ResultRetention,
    TextPolicy,
    ToolDeclarationRecord,
    ToolExecutionStatus,
    ToolResultRecord,
    ToolSkipReason,
    TriggerKind,
    TurnOutputStatus,
    TurnResponseRecord,
    new_agent_id,
)
from quickquip.llm.store_parts._base import _utc_now

logger = logging.getLogger(__name__)

_AGENT_SCHEMA_VERSION = 1

# 逐条执行（§4.3.1：迁移事务内不得 executescript 隐式提交）。
_AGENT_SCHEMA_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS agent_scopes (
        scope_key TEXT PRIMARY KEY,
        generation INTEGER NOT NULL DEFAULT 0,
        history_revision INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_loops (
        loop_id TEXT PRIMARY KEY,
        scope_key TEXT NOT NULL,
        bot_self_id TEXT,
        scope_generation INTEGER NOT NULL,
        anchor_row_id INTEGER UNIQUE,
        trigger_kind TEXT NOT NULL,
        started_at TEXT NOT NULL,
        closed_at TEXT,
        status TEXT NOT NULL,
        terminal_reason TEXT,
        record_version INTEGER NOT NULL,
        record_bytes INTEGER NOT NULL DEFAULT 0,
        replay_revision INTEGER NOT NULL DEFAULT 0,
        legacy INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (scope_key) REFERENCES agent_scopes(scope_key)
    )
    """,
    # 同 scope 最多一个未关闭 Loop（§4.1）。
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_loops_one_open
    ON agent_loops(scope_key) WHERE closed_at IS NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_loops_scope_anchor
    ON agent_loops(scope_key, anchor_row_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_loops_closed_at
    ON agent_loops(scope_key, closed_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_turns (
        turn_id TEXT PRIMARY KEY,
        loop_id TEXT NOT NULL,
        turn_index INTEGER NOT NULL,
        message_row_id INTEGER UNIQUE,
        parts_json TEXT NOT NULL,
        native_state_json TEXT,
        native_omission_reason TEXT,
        owner_json TEXT,
        finish_reason TEXT,
        committed_at TEXT NOT NULL,
        delivery_policy TEXT NOT NULL,
        text_policy TEXT NOT NULL,
        output_status TEXT NOT NULL,
        FOREIGN KEY (loop_id) REFERENCES agent_loops(loop_id) ON DELETE CASCADE,
        UNIQUE (loop_id, turn_index)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_tool_executions (
        execution_id TEXT PRIMARY KEY,
        turn_id TEXT NOT NULL,
        call_index INTEGER NOT NULL,
        provider_call_id TEXT,
        tool_name TEXT NOT NULL,
        arguments_json TEXT,
        arguments_omission_reason TEXT,
        status TEXT NOT NULL,
        result_json TEXT,
        result_retention TEXT NOT NULL,
        result_omission_reason TEXT,
        outbound_media_json TEXT,
        started_at TEXT,
        finished_at TEXT,
        FOREIGN KEY (turn_id) REFERENCES agent_turns(turn_id) ON DELETE CASCADE,
        UNIQUE (turn_id, call_index)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_deliveries (
        delivery_id TEXT PRIMARY KEY,
        loop_id TEXT NOT NULL,
        turn_id TEXT,
        tool_execution_id TEXT,
        kind TEXT NOT NULL,
        delivery_index INTEGER NOT NULL,
        chunk_index INTEGER,
        source_start INTEGER,
        source_end INTEGER,
        wrappers_json TEXT,
        attachment_refs_json TEXT,
        notice_text TEXT,
        status TEXT NOT NULL,
        recall_status TEXT NOT NULL DEFAULT 'active',
        planned_at TEXT NOT NULL,
        FOREIGN KEY (loop_id) REFERENCES agent_loops(loop_id) ON DELETE CASCADE,
        FOREIGN KEY (turn_id) REFERENCES agent_turns(turn_id) ON DELETE CASCADE,
        FOREIGN KEY (tool_execution_id)
            REFERENCES agent_tool_executions(execution_id) ON DELETE CASCADE,
        UNIQUE (loop_id, delivery_index)
    )
    """,
    # 文字 Chunk 专用：一个 Chunk 只属于一个 Turn（§3.2.1）。
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_deliveries_turn_chunk
    ON agent_deliveries(turn_id, chunk_index)
    WHERE turn_id IS NOT NULL AND chunk_index IS NOT NULL
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_delivery_attempts (
        attempt_id TEXT PRIMARY KEY,
        delivery_id TEXT NOT NULL,
        attempt_index INTEGER NOT NULL,
        status TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        qq_message_id TEXT,
        error_code TEXT,
        FOREIGN KEY (delivery_id) REFERENCES agent_deliveries(delivery_id) ON DELETE CASCADE,
        UNIQUE (delivery_id, attempt_index)
    )
    """,
    # QQ ID 查询必须带 scope 谓词（§4.1），不假设跨群全局唯一。
    """
    CREATE INDEX IF NOT EXISTS idx_agent_attempts_qq_message_id
    ON agent_delivery_attempts(qq_message_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    )
    """,
)

_TEXT_PART_ORIGINS = {"model", "source_annotation"}


class AgentStoreError(RuntimeError):
    """Agent 记录领域的基类错误。"""


class ScopeGenerationMismatch(AgentStoreError):
    """写入时的 scope generation 已失效（清空/撤回/切会话后迟到写入）。"""


class LoopNotWritable(AgentStoreError):
    """目标 Loop 已关闭或状态不允许该写入。"""


class StaleRevision(AgentStoreError):
    """mutate_history 的期望 revision 与库中不一致（并发编辑屏障）。"""


class LoopRecordBudgetExceeded(AgentStoreError):
    """单 Loop 业务记录字节触顶（§8.4）；调用方应终止 Loop 并记录事实。"""


class HistoryMutation:
    """历史失效语义（§4.1）：generation 类使旧写入屏障失效，revision 类只
    表示内容编辑。调用方以数据库值为最终屏障，进程内缓存不算数。"""

    CLEAR = "clear"  # generation+1 revision+1
    SESSION_SWITCH = "session_switch"  # generation+1
    RECALL = "recall"  # generation+1
    EDIT = "edit"  # revision+1
    DELETE = "delete"  # revision+1


_GENERATION_MUTATIONS = {
    HistoryMutation.CLEAR,
    HistoryMutation.SESSION_SWITCH,
    HistoryMutation.RECALL,
}


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _utf8_bytes(text: str | None) -> int:
    return 0 if text is None else len(text.encode("utf-8"))


def _utf8_head_tail(text: str, budget: int) -> tuple[str, list[tuple[int, int]]]:
    """UTF-8 安全的首尾摘录（§8.4）：超限结果保留首尾，按 code point 边界切。

    返回 ``(excerpt, retained_ranges)``，ranges 为原串 code point 区间。
    摘录含省略标记，标记字节计入预算（预留 64 字节 + 位数余量）。
    """
    if _utf8_bytes(text) <= budget:
        return text, [(0, len(text))]
    marker_reserve = 64 + 16
    half = max(0, (budget - marker_reserve) // 2)
    head_end = len(text)
    head_bytes = 0
    for index, char in enumerate(text):
        width = len(char.encode("utf-8"))
        if head_bytes + width > half:
            head_end = index
            break
        head_bytes += width
    tail_start = len(text)
    tail_bytes = 0
    for index in range(len(text) - 1, -1, -1):
        width = len(text[index].encode("utf-8"))
        if tail_bytes + width > half or index <= head_end:
            break
        tail_bytes += width
        tail_start = index
    omitted = len(text) - head_end - (len(text) - tail_start)
    excerpt = text[:head_end] + f"…[省略 {omitted} 字符]…" + text[tail_start:]
    while _utf8_bytes(excerpt) > budget and tail_start < len(text):
        # 极端兜底：标记位数超出预留时从尾部逐字符再收。
        tail_start += 1
        omitted = len(text) - head_end - (len(text) - tail_start)
        excerpt = text[:head_end] + f"…[省略 {omitted} 字符]…" + text[tail_start:]
    ranges = [(0, head_end), (tail_start, len(text))] if tail_start < len(text) else [(0, head_end)]
    return excerpt, ranges


@dataclass(frozen=True, slots=True)
class UserTriggerPayload:
    """新 Loop 的 user 触发行载荷（§5.3.1：过滤后冻结的 user 表达）。"""

    user_id: str | None
    sender_name: str = ""
    canonical_name: str = ""
    content: str = ""
    raw_content: str = ""
    message_id: str | None = None


@dataclass(frozen=True, slots=True)
class LoopHandle:
    loop_id: str
    scope_key: str
    scope_generation: int
    trigger_kind: TriggerKind


@dataclass(frozen=True, slots=True)
class TurnRecord:
    turn_id: str
    turn_index: int
    message_row_id: int
    delivery_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AttemptHandle:
    attempt_id: str
    delivery_id: str
    attempt_index: int


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """D5 三上限（§2 默认值由 runtime 配置解析提供）。"""

    retention_days: int = 30
    max_loops: int = 1000
    max_bytes: int = 67_108_864


@dataclass(frozen=True, slots=True)
class PruneReport:
    deleted_loop_ids: tuple[str, ...] = ()
    # 硬上限仍无法满足时需要推进的活动纪元锚点（调用方负责 reset，§8.4）。
    blocked_active_anchors: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    closed_loops: tuple[str, ...] = ()
    tools_not_executed: tuple[str, ...] = ()
    tools_indeterminate: tuple[str, ...] = ()
    deliveries_skipped: tuple[str, ...] = ()
    deliveries_unknown: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LoadedToolExecution:
    execution_id: str
    call_index: int
    provider_call_id: str | None
    tool_name: str
    arguments_json: str | None
    arguments_omission_reason: str | None
    status: str
    result: dict[str, Any] | None
    result_retention: str
    result_omission_reason: str | None
    outbound_media: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class LoadedDelivery:
    delivery_id: str
    kind: str
    turn_id: str | None
    tool_execution_id: str | None
    chunk_index: int | None
    source_start: int | None
    source_end: int | None
    status: str
    recall_status: str
    qq_message_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LoadedTurn:
    turn_id: str
    turn_index: int
    message_row_id: int
    text: str
    parts: tuple[dict[str, Any], ...]
    native_state: dict[str, Any] | None
    native_omission_reason: str | None
    owner: dict[str, Any] | None
    finish_reason: str | None
    text_policy: str
    output_status: str
    delivery_policy: str
    tools: tuple[LoadedToolExecution, ...]
    deliveries: tuple[LoadedDelivery, ...]


@dataclass(frozen=True, slots=True)
class LoadedLoop:
    loop_id: str
    scope_key: str
    anchor_row_id: int
    trigger_kind: str
    started_at: str
    closed_at: str | None
    status: str
    terminal_reason: str | None
    legacy: bool
    replay_revision: int
    record_bytes: int
    user_row: dict[str, Any]
    turns: tuple[LoadedTurn, ...]
    # Loop 级全部交付（含 turn 为空的 host_notice / 归因于他 Turn 的条目）。
    deliveries: tuple[LoadedDelivery, ...] = ()


class AgentRecordsStoreMixin:
    """Agent 执行记录域。依赖 _StoreBase 的 _connect / _unavailable。"""

    # ── schema 与迁移 ────────────────────────────────────────────

    def _ensure_agent_schema(self) -> None:
        """并发安全的 agent schema 迁移（§4.3.1-2）。

        ``BEGIN IMMEDIATE`` 取写锁后检查版本表；Bot/Web 同时首开只有一方
        执行迁移。失败回滚，不留半迁移。
        """
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            applied = conn.execute(
                "SELECT version FROM agent_schema_migrations"
            ).fetchall() if self._agent_table_exists(conn, "agent_schema_migrations") else []
            applied_versions = {int(row["version"]) for row in applied}
            if _AGENT_SCHEMA_VERSION not in applied_versions:
                for statement in _AGENT_SCHEMA_DDL:
                    conn.execute(statement)
                self._add_agent_conversation_columns(conn)
                self._backfill_legacy_loops(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO agent_schema_migrations (version, applied_at) VALUES (?, ?)",
                    (_AGENT_SCHEMA_VERSION, _utc_now()),
                )
                self._verify_agent_schema(conn)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _agent_table_exists(conn: sqlite3.Connection, table: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        return row is not None

    @staticmethod
    def _add_agent_conversation_columns(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(conversation_messages)")
        }
        if "agent_loop_id" not in columns:
            conn.execute("ALTER TABLE conversation_messages ADD COLUMN agent_loop_id TEXT")
        if "agent_turn_id" not in columns:
            conn.execute("ALTER TABLE conversation_messages ADD COLUMN agent_turn_id TEXT")

    def _backfill_legacy_loops(self, conn: sqlite3.Connection) -> None:
        """旧行按 user 锚点分组回填 legacy Loop/Turn/delivery（§4.3.3-6）。

        每 scope 按 row ID 升序：一个 user 行及其后到下个 user 行前的
        assistant 行为一个 legacy Loop；开头没有 user 的 assistant 连续段
        归一个 ``legacy_orphan`` Loop。原行 ID、正文、身份与时间原样保留，
        不制造历史工具、thinking 或 owner。
        """
        scopes = [
            row["group_id"]
            for row in conn.execute(
                "SELECT DISTINCT group_id FROM conversation_messages ORDER BY group_id"
            )
        ]
        for scope_key in scopes:
            conn.execute(
                "INSERT OR IGNORE INTO agent_scopes (scope_key) VALUES (?)", (scope_key,)
            )
            rows = conn.execute(
                """
                SELECT id, user_id, sender_name, canonical_name, role, content,
                       message_id, raw_content, created_at
                FROM conversation_messages
                WHERE group_id = ?
                ORDER BY id ASC
                """,
                (scope_key,),
            ).fetchall()
            groups: list[list[sqlite3.Row]] = []
            current: list[sqlite3.Row] = []
            for row in rows:
                if row["role"] == "user":
                    if current:
                        groups.append(current)
                    current = [row]
                else:
                    current.append(row)
            if current:
                groups.append(current)

            for group in groups:
                self._backfill_one_legacy_group(conn, scope_key, group)

    @staticmethod
    def _backfill_one_legacy_group(
        conn: sqlite3.Connection, scope_key: str, group: list[sqlite3.Row]
    ) -> None:
        first = group[0]
        is_orphan = first["role"] != "user"
        if is_orphan:
            loop_id = f"legacy_orphan_{int(first['id'])}"
            trigger = TriggerKind.LEGACY_ORPHAN
            anchor_row_id = None
            started_at = first["created_at"]
        else:
            loop_id = f"legacy_{int(first['id'])}"
            trigger = TriggerKind.LEGACY
            anchor_row_id = int(first["id"])
            started_at = first["created_at"]
        closed_at = group[-1]["created_at"]
        record_bytes = sum(
            _utf8_bytes(row["content"]) + _utf8_bytes(row["raw_content"]) for row in group
        )
        conn.execute(
            """
            INSERT INTO agent_loops (loop_id, scope_key, bot_self_id, scope_generation,
                                     anchor_row_id, trigger_kind, started_at, closed_at,
                                     status, terminal_reason, record_version, record_bytes,
                                     replay_revision, legacy)
            VALUES (?, ?, NULL, 0, ?, ?, ?, ?, ?, NULL, ?, ?, 0, 1)
            """,
            (
                loop_id, scope_key, anchor_row_id, trigger, started_at, closed_at,
                LoopStatus.LEGACY, AGENT_RECORD_VERSION, record_bytes,
            ),
        )
        if anchor_row_id is not None:
            conn.execute(
                "UPDATE conversation_messages SET agent_loop_id = ? WHERE id = ?",
                (loop_id, anchor_row_id),
            )

        delivery_index = 0
        for turn_index, row in enumerate(group):
            if row["role"] != "assistant":
                continue
            turn_id = f"legacy_turn_{int(row['id'])}"
            text = row["content"] or ""
            parts = _dumps(
                {
                    "version": AGENT_RECORD_VERSION,
                    "parts": [{"type": "text_ref", "start": 0, "end": len(text), "origin": "model"}],
                }
            )
            conn.execute(
                """
                INSERT INTO agent_turns (turn_id, loop_id, turn_index, message_row_id,
                                         parts_json, delivery_policy, text_policy,
                                         output_status, committed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id, loop_id, turn_index, int(row["id"]), parts,
                    DeliveryPolicy.FINAL_ONLY, TextPolicy.ALLOWED,
                    TurnOutputStatus.VISIBLE, row["created_at"],
                ),
            )
            conn.execute(
                "UPDATE conversation_messages SET agent_loop_id = ?, agent_turn_id = ? WHERE id = ?",
                (loop_id, turn_id, int(row["id"])),
            )
            qq_id = row["message_id"]
            status = DeliveryStatus.SENT if qq_id else DeliveryStatus.LEGACY_UNTRACKED
            delivery_id = f"legacy_delivery_{int(row['id'])}"
            conn.execute(
                """
                INSERT INTO agent_deliveries (delivery_id, loop_id, turn_id, kind,
                                              delivery_index, chunk_index, source_start,
                                              source_end, status, recall_status, planned_at)
                VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, 'active', ?)
                """,
                (
                    delivery_id, loop_id, turn_id, DeliveryKind.TEXT_CHUNK,
                    delivery_index, len(text), status, row["created_at"],
                ),
            )
            delivery_index += 1
            if qq_id:
                conn.execute(
                    """
                    INSERT INTO agent_delivery_attempts (attempt_id, delivery_id, attempt_index,
                                                         status, started_at, finished_at, qq_message_id)
                    VALUES (?, ?, 0, ?, ?, ?, ?)
                    """,
                    (
                        f"legacy_attempt_{int(row['id'])}", delivery_id,
                        DeliveryStatus.SENT, row["created_at"], row["created_at"], str(qq_id),
                    ),
                )

    @staticmethod
    def _verify_agent_schema(conn: sqlite3.Connection) -> None:
        """迁移后完整性检查（§4.3.7）：FK、唯一约束抽查与侧表孤儿。"""
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise sqlite3.IntegrityError(f"agent schema 迁移后 foreign_key_check 失败：{violations[:3]}")
        orphans = conn.execute(
            """
            SELECT COUNT(*) AS c FROM agent_turns t
            LEFT JOIN conversation_messages m ON m.id = t.message_row_id
            WHERE t.message_row_id IS NOT NULL AND m.id IS NULL
            """
        ).fetchone()
        if orphans and int(orphans["c"]):
            raise sqlite3.IntegrityError("agent 迁移出现指向不存在主行的 Turn")

    # ── scope 状态 ───────────────────────────────────────────────

    def agent_scope_state(self, scope_key: str) -> tuple[int, int]:
        """读取 (generation, history_revision)；scope 未见时为 (0, 0)。"""
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT generation, history_revision FROM agent_scopes WHERE scope_key = ?",
                (scope_key,),
            ).fetchone()
        if row is None:
            return 0, 0
        return int(row["generation"]), int(row["history_revision"])

    def mutate_history(
        self,
        scope_key: str,
        expected_revision: int,
        mutation: str,
    ) -> tuple[int, int]:
        """历史失效屏障（§4.2）：返回新 (generation, revision)。

        期望 revision 不一致抛 ``StaleRevision``——并发编辑在数据库层
        串行化，进程内缓存不算数。
        """
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR IGNORE INTO agent_scopes (scope_key) VALUES (?)", (scope_key,)
            )
            row = conn.execute(
                "SELECT generation, history_revision FROM agent_scopes WHERE scope_key = ?",
                (scope_key,),
            ).fetchone()
            generation, revision = int(row["generation"]), int(row["history_revision"])
            if revision != expected_revision:
                conn.rollback()
                raise StaleRevision(
                    f"scope={scope_key} 期望 revision={expected_revision} 实际={revision}"
                )
            if mutation in _GENERATION_MUTATIONS:
                generation += 1
            revision += 1
            conn.execute(
                "UPDATE agent_scopes SET generation = ?, history_revision = ? WHERE scope_key = ?",
                (generation, revision, scope_key),
            )
            conn.commit()
            return generation, revision
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Loop 生命周期 ────────────────────────────────────────────

    def begin_loop(
        self,
        scope_key: str,
        expected_generation: int,
        trigger: TriggerKind,
        user: UserTriggerPayload,
        *,
        bot_self_id: str | None = None,
    ) -> LoopHandle:
        """创建 Loop 与 user 触发行（§4.2：先临时空 anchor，再回填并验证）。

        generation 失效时抛 ``ScopeGenerationMismatch``；同 scope 已有未
        关闭 Loop 时抛 ``LoopNotWritable``。
        """
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        loop_id = new_agent_id("loop")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR IGNORE INTO agent_scopes (scope_key) VALUES (?)", (scope_key,))
            scope = conn.execute(
                "SELECT generation FROM agent_scopes WHERE scope_key = ?", (scope_key,)
            ).fetchone()
            generation = int(scope["generation"])
            if generation != expected_generation:
                conn.rollback()
                raise ScopeGenerationMismatch(
                    f"scope={scope_key} loop 创建被拒：generation {expected_generation} -> {generation}"
                )
            open_loop = conn.execute(
                "SELECT loop_id FROM agent_loops WHERE scope_key = ? AND closed_at IS NULL",
                (scope_key,),
            ).fetchone()
            if open_loop is not None:
                conn.rollback()
                raise LoopNotWritable(f"scope={scope_key} 已有未关闭 Loop {open_loop['loop_id']}")
            conn.execute(
                """
                INSERT INTO agent_loops (loop_id, scope_key, bot_self_id, scope_generation,
                                         trigger_kind, started_at, status, record_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    loop_id, scope_key, bot_self_id, generation, trigger,
                    _utc_now(), LoopStatus.RUNNING, AGENT_RECORD_VERSION,
                ),
            )
            anchor_row_id = self._insert_user_row(conn, scope_key, loop_id, user)
            conn.execute(
                "UPDATE agent_loops SET anchor_row_id = ? WHERE loop_id = ?",
                (anchor_row_id, loop_id),
            )
            bound = conn.execute(
                "SELECT anchor_row_id FROM agent_loops WHERE loop_id = ?", (loop_id,)
            ).fetchone()
            if bound is None or bound["anchor_row_id"] != anchor_row_id:
                conn.rollback()
                raise AgentStoreError(f"loop={loop_id} anchor 绑定验证失败")
            conn.commit()
            return LoopHandle(
                loop_id=loop_id,
                scope_key=scope_key,
                scope_generation=generation,
                trigger_kind=trigger,
            )
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _insert_user_row(
        conn: sqlite3.Connection, scope_key: str, loop_id: str, user: UserTriggerPayload
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO conversation_messages
                (group_id, user_id, sender_name, canonical_name, role, content,
                 message_id, raw_content, created_at, agent_loop_id)
            VALUES (?, ?, ?, ?, 'user', ?, ?, ?, ?, ?)
            """,
            (
                scope_key,
                user.user_id,
                user.sender_name.strip() or None,
                user.canonical_name.strip() or None,
                user.content,
                user.message_id,
                user.raw_content or None,
                _utc_now(),
                loop_id,
            ),
        )
        return int(cursor.lastrowid)

    def _validate_loop_writable(
        self, conn: sqlite3.Connection, handle: LoopHandle
    ) -> None:
        row = conn.execute(
            "SELECT status, closed_at, scope_generation FROM agent_loops WHERE loop_id = ?",
            (handle.loop_id,),
        ).fetchone()
        if row is None:
            raise LoopNotWritable(f"loop={handle.loop_id} 不存在")
        if row["closed_at"] is not None or row["status"] != LoopStatus.RUNNING:
            raise LoopNotWritable(f"loop={handle.loop_id} 已关闭（{row['status']}）")
        scope = conn.execute(
            "SELECT generation FROM agent_scopes WHERE scope_key = ?",
            (handle.scope_key,),
        ).fetchone()
        current = int(scope["generation"]) if scope is not None else 0
        if current != handle.scope_generation:
            raise ScopeGenerationMismatch(
                f"loop={handle.loop_id} 写入被拒：scope generation "
                f"{handle.scope_generation} -> {current}"
            )

    def commit_turn(
        self,
        handle: LoopHandle,
        response: TurnResponseRecord,
        tool_declarations: Sequence[ToolDeclarationRecord],
        delivery_plan: Sequence[DeliveryPlanItem],
        *,
        delivery_policy: DeliveryPolicy = DeliveryPolicy.ALL_TURNS,
        turn_id: str | None = None,
    ) -> TurnRecord:
        """原子提交一个 Turn：主表 assistant 行 + Turn + 工具声明 + 交付计划。

        事务提交成功之后调用方才允许发送或执行工具（§5.3.5）。parts 的
        文本范围/工具/native 引用在此验证（§4.4），缺失引用直接失败而非
        静默吞掉。单 Loop 字节账本在此累加，触顶抛 ``LoopRecordBudgetExceeded``。
        ``turn_id`` 可由调用方预生成（交付计划需要在提交前引用它）；缺省
        由 store 生成。
        """
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        turn_id = turn_id or new_agent_id("turn")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._validate_loop_writable(conn, handle)
            text = response.text
            parts_payload = self._validated_parts(
                text, response.parts, tool_declarations, response.native_state,
                response.native_omission_reason,
            )
            native_json = self._bounded_native_json(response)

            index_row = conn.execute(
                "SELECT COALESCE(MAX(turn_index), -1) + 1 AS next FROM agent_turns WHERE loop_id = ?",
                (handle.loop_id,),
            ).fetchone()
            turn_index = int(index_row["next"])

            cursor = conn.execute(
                """
                INSERT INTO conversation_messages
                    (group_id, user_id, role, content, created_at, agent_loop_id, agent_turn_id)
                VALUES (?, NULL, 'assistant', ?, ?, ?, ?)
                """,
                (handle.scope_key, text, _utc_now(), handle.loop_id, turn_id),
            )
            message_row_id = int(cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO agent_turns (turn_id, loop_id, turn_index, message_row_id,
                                         parts_json, native_state_json, native_omission_reason,
                                         owner_json, finish_reason, committed_at,
                                         delivery_policy, text_policy, output_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id, handle.loop_id, turn_index, message_row_id,
                    parts_payload, native_json,
                    None if response.native_omission_reason is None else str(response.native_omission_reason),
                    _dumps(response.owner) if response.owner is not None else None,
                    response.finish_reason, _utc_now(),
                    delivery_policy, response.text_policy, response.output_status,
                ),
            )
            for declaration in tool_declarations:
                self._insert_tool_declaration(conn, handle, turn_id, declaration)

            delivery_ids = self._insert_delivery_plan(
                conn, handle, turn_id, delivery_plan, text,
            )

            added_bytes = (
                _utf8_bytes(text) + _utf8_bytes(parts_payload) + _utf8_bytes(native_json)
                + sum(
                    _utf8_bytes(d.arguments_json) + _utf8_bytes(d.tool_name)
                    for d in tool_declarations
                )
                + sum(_utf8_bytes(p.notice_text or "") for p in delivery_plan)
            )
            loop_row = conn.execute(
                "SELECT record_bytes FROM agent_loops WHERE loop_id = ?", (handle.loop_id,)
            ).fetchone()
            new_total = int(loop_row["record_bytes"]) + added_bytes
            if new_total > MAX_LOOP_RECORD_BYTES:
                conn.rollback()
                raise LoopRecordBudgetExceeded(
                    f"loop={handle.loop_id} 记录字节 {new_total} 超过 {MAX_LOOP_RECORD_BYTES}"
                )
            conn.execute(
                "UPDATE agent_loops SET record_bytes = ? WHERE loop_id = ?",
                (new_total, handle.loop_id),
            )
            conn.commit()
            return TurnRecord(
                turn_id=turn_id,
                turn_index=turn_index,
                message_row_id=message_row_id,
                delivery_ids=tuple(delivery_ids),
            )
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _validated_parts(
        text: str,
        parts: Sequence[dict[str, Any]],
        tool_declarations: Sequence[ToolDeclarationRecord],
        native_state: dict[str, Any] | None,
        native_omission_reason: NativeOmissionReason | None,
    ) -> str:
        execution_ids = {d.execution_id for d in tool_declarations}
        native_count = 0
        if native_state is not None and native_omission_reason is None:
            blocks = native_state.get("blocks")
            if isinstance(blocks, list):
                native_count = len(blocks)
        validated: list[dict[str, Any]] = []
        for part in parts:
            kind = part.get("type")
            if kind == "text_ref":
                start, end, origin = int(part["start"]), int(part["end"]), part.get("origin", "model")
                if not (0 <= start <= end <= len(text)):
                    raise AgentStoreError(f"text_ref 范围 [{start},{end}) 超出已存正文长度 {len(text)}")
                if origin not in _TEXT_PART_ORIGINS:
                    raise AgentStoreError(f"text_ref origin 非法：{origin}")
                validated.append({"type": "text_ref", "start": start, "end": end, "origin": origin})
            elif kind == "tool_ref":
                if part["execution_id"] not in execution_ids:
                    raise AgentStoreError(f"tool_ref 指向未声明执行 {part['execution_id']}")
                validated.append({"type": "tool_ref", "execution_id": part["execution_id"]})
            elif kind == "native_ref":
                index = int(part["index"])
                if native_count == 0 or not (0 <= index < native_count):
                    raise AgentStoreError(f"native_ref index {index} 超出原生块数量 {native_count}")
                validated.append({"type": "native_ref", "index": index})
            else:
                raise AgentStoreError(f"parts 含未知类型：{kind}")
        return _dumps({"version": AGENT_RECORD_VERSION, "parts": validated})

    @staticmethod
    def _bounded_native_json(response: TurnResponseRecord) -> str | None:
        if response.native_state is None:
            return None
        if response.native_omission_reason is not None:
            # 决策已由运行期做出：省略原生副本，保留通用事实（§2 MAX_NATIVE_STATE_BYTES）。
            return None
        payload = dict(response.native_state)
        payload.setdefault("version", AGENT_RECORD_VERSION)
        encoded = _dumps(payload)
        if _utf8_bytes(encoded) > MAX_NATIVE_STATE_BYTES:
            raise AgentStoreError(
                "native_state 超限且未声明省略原因；调用方必须先按 MAX_NATIVE_STATE_BYTES 预检"
            )
        return encoded

    @staticmethod
    def _insert_tool_declaration(
        conn: sqlite3.Connection,
        handle: LoopHandle,
        turn_id: str,
        declaration: ToolDeclarationRecord,
    ) -> None:
        arguments_json = declaration.arguments_json
        omission = declaration.arguments_omission_reason
        if arguments_json is not None and _utf8_bytes(arguments_json) > MAX_PERSISTED_TOOL_ARGUMENT_BYTES:
            arguments_json = None
            omission = "size_limit"
        conn.execute(
            """
            INSERT INTO agent_tool_executions (execution_id, turn_id, call_index,
                                               provider_call_id, tool_name, arguments_json,
                                               arguments_omission_reason, status,
                                               result_retention)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                declaration.execution_id, turn_id, declaration.call_index,
                declaration.provider_call_id, declaration.tool_name, arguments_json,
                None if omission is None else str(omission),
                ToolExecutionStatus.DECLARED, ResultRetention.BOUNDED,
            ),
        )

    @staticmethod
    def _insert_delivery_plan(
        conn: sqlite3.Connection,
        handle: LoopHandle,
        turn_id: str,
        delivery_plan: Sequence[DeliveryPlanItem],
        turn_text: str,
    ) -> list[str]:
        index_row = conn.execute(
            "SELECT COALESCE(MAX(delivery_index), -1) + 1 AS next FROM agent_deliveries WHERE loop_id = ?",
            (handle.loop_id,),
        ).fetchone()
        delivery_index = int(index_row["next"])
        delivery_ids: list[str] = []
        for item in delivery_plan:
            if item.kind == DeliveryKind.TEXT_CHUNK:
                if item.turn_id is not None and item.turn_id != turn_id:
                    raise AgentStoreError("文字 delivery 的 turn 归属与提交 Turn 不一致")
                if item.source_start is None or item.source_end is None:
                    raise AgentStoreError("文字 delivery 缺少源范围")
                if not (0 <= item.source_start <= item.source_end <= len(turn_text)):
                    raise AgentStoreError(
                        f"文字 delivery 源范围 [{item.source_start},{item.source_end}) 超出正文"
                    )
            elif item.kind == DeliveryKind.TOOL_MEDIA:
                if item.tool_execution_id is None:
                    raise AgentStoreError("tool_media delivery 缺少 tool_execution_id")
            elif item.kind == DeliveryKind.HOST_NOTICE:
                if not (item.notice_text or "").strip():
                    raise AgentStoreError("host_notice delivery 缺少 notice_text")
            else:
                raise AgentStoreError(f"未知交付类型：{item.kind}")
            delivery_id = item.delivery_id or new_agent_id("dlv")
            conn.execute(
                """
                INSERT INTO agent_deliveries (delivery_id, loop_id, turn_id, tool_execution_id,
                                              kind, delivery_index, chunk_index, source_start,
                                              source_end, wrappers_json, attachment_refs_json,
                                              notice_text, status, recall_status, planned_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    delivery_id, handle.loop_id,
                    turn_id if item.kind != DeliveryKind.HOST_NOTICE else item.turn_id,
                    item.tool_execution_id, item.kind, delivery_index, item.chunk_index,
                    item.source_start, item.source_end,
                    _dumps({"version": AGENT_RECORD_VERSION, "prefix": item.wrappers[0], "suffix": item.wrappers[1]}),
                    _dumps({"version": AGENT_RECORD_VERSION, "refs": [list(ref) for ref in item.attachment_refs]}),
                    item.notice_text, DeliveryStatus.PLANNED, _utc_now(),
                ),
            )
            delivery_ids.append(delivery_id)
            delivery_index += 1
        return delivery_ids

    # ── 工具执行状态 ─────────────────────────────────────────────

    def mark_tool_started(self, handle: LoopHandle, execution_id: str) -> None:
        """执行前预写 running（§4.2：开始工具的预写状态事务）。"""
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._validate_loop_writable(conn, handle)
            status = self._tool_status(conn, handle, execution_id)
            if status != ToolExecutionStatus.DECLARED:
                raise LoopNotWritable(f"execution={execution_id} 状态 {status} 不允许开始执行")
            conn.execute(
                "UPDATE agent_tool_executions SET status = ?, started_at = ? WHERE execution_id = ?",
                (ToolExecutionStatus.RUNNING, _utc_now(), execution_id),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def finish_tool(
        self,
        handle: LoopHandle,
        execution_id: str,
        result: ToolResultRecord | None,
        *,
        status: ToolExecutionStatus | None = None,
        skip_reason: ToolSkipReason | None = None,
        result_retention: ResultRetention = ResultRetention.BOUNDED,
        outbound_media: Sequence[dict[str, Any]] = (),
    ) -> None:
        """工具终态写入（§4.2/§8.4）。

        - ``result`` 非 None：按字节上限持久化（ephemeral 永不存正文，
          D1）；超限走 UTF-8 安全首尾摘录并记 original_bytes 与省略原因。
        - ``result=None`` + ``status=NOT_EXECUTED``：未执行终态（限额/
          阻断/恢复），``skip_reason`` 记入 result_json 的 detail 字段。
        - Loop 已关闭时的迟到结果：目标记录仍在则记录无正文的已知终态
          并提升该 Loop 的 replay_revision（§4.2）。
        """
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            closed = self._loop_closed(conn, handle)
            if not closed:
                self._validate_loop_writable(conn, handle)
            exists = conn.execute(
                "SELECT 1 FROM agent_tool_executions WHERE execution_id = ?", (execution_id,)
            ).fetchone()
            if exists is None:
                # 目标记录已删除：只记脱敏诊断，不创建新历史（§4.2）。
                logger.warning(
                    "迟到工具结果指向已删除 execution=%s loop=%s（只记诊断）",
                    execution_id, handle.loop_id,
                )
                conn.rollback()
                return
            current = self._tool_status(conn, handle, execution_id)
            terminal_status = status if status is not None else (
                result.status if result is not None else ToolExecutionStatus.NOT_EXECUTED
            )
            if current in (ToolExecutionStatus.SUCCEEDED, ToolExecutionStatus.FAILED,
                           ToolExecutionStatus.NOT_EXECUTED):
                conn.rollback()
                raise LoopNotWritable(f"execution={execution_id} 已是终态 {current}")
            result_json = self._bounded_result_json(
                result, result_retention, skip_reason,
            )
            media_json = (
                _dumps({"version": AGENT_RECORD_VERSION, "items": list(outbound_media)})
                if outbound_media else None
            )
            added_bytes = _utf8_bytes(result_json) + _utf8_bytes(media_json)
            conn.execute(
                """
                UPDATE agent_tool_executions
                SET status = ?, result_json = ?, result_retention = ?,
                    outbound_media_json = ?, finished_at = ?,
                    result_omission_reason = COALESCE(result_omission_reason, ?)
                WHERE execution_id = ?
                """,
                (
                    terminal_status, result_json, result_retention, media_json,
                    _utc_now(),
                    self._result_omission(result, result_retention, skip_reason),
                    execution_id,
                ),
            )
            if closed:
                conn.execute(
                    "UPDATE agent_loops SET replay_revision = replay_revision + 1 WHERE loop_id = ?",
                    (handle.loop_id,),
                )
            else:
                conn.execute(
                    "UPDATE agent_loops SET record_bytes = record_bytes + ? WHERE loop_id = ?",
                    (added_bytes, handle.loop_id),
                )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _result_omission(
        result: ToolResultRecord | None,
        retention: ResultRetention,
        skip_reason: ToolSkipReason | None,
    ) -> str | None:
        if skip_reason is not None:
            return None
        if result is None:
            return None
        if retention == ResultRetention.EPHEMERAL:
            return str(ResultOmissionReason.EPHEMERAL_POLICY)
        if _utf8_bytes(result.content) > MAX_PERSISTED_TOOL_RESULT_BYTES:
            return str(ResultOmissionReason.SIZE_LIMIT)
        return None

    @staticmethod
    def _bounded_result_json(
        result: ToolResultRecord | None,
        retention: ResultRetention,
        skip_reason: ToolSkipReason | None,
    ) -> str:
        if skip_reason is not None:
            payload: dict[str, Any] = {
                "version": AGENT_RECORD_VERSION,
                "content": "",
                "is_error": False,
                "original_bytes": 0,
                "retained_ranges": [],
                "media_descriptions": [],
                "detail": str(skip_reason),
            }
            return _dumps(payload)
        if result is None:
            raise AgentStoreError("finish_tool 需要 result 或显式终态")
        if retention == ResultRetention.EPHEMERAL:
            # D1：查询正文/hits/cursor 禁止进入业务持久层，只留事实与省略说明。
            payload = {
                "version": AGENT_RECORD_VERSION,
                "content": "",
                "is_error": bool(result.is_error),
                "original_bytes": int(result.original_bytes),
                "retained_ranges": [],
                "media_descriptions": [],
                "retention": str(ResultRetention.EPHEMERAL),
            }
            return _dumps(payload)
        content = result.content
        retained = list(result.retained_ranges)
        if _utf8_bytes(content) > MAX_PERSISTED_TOOL_RESULT_BYTES:
            content, retained = _utf8_head_tail(content, MAX_PERSISTED_TOOL_RESULT_BYTES)
        payload = {
            "version": AGENT_RECORD_VERSION,
            "content": content,
            "is_error": bool(result.is_error),
            "original_bytes": int(result.original_bytes),
            "retained_ranges": [list(rng) for rng in retained],
            "media_descriptions": list(result.media_descriptions),
        }
        return _dumps(payload)

    @staticmethod
    def _tool_status(conn: sqlite3.Connection, handle: LoopHandle, execution_id: str) -> str:
        row = conn.execute(
            """
            SELECT e.status FROM agent_tool_executions e
            JOIN agent_turns t ON t.turn_id = e.turn_id
            WHERE e.execution_id = ? AND t.loop_id = ?
            """,
            (execution_id, handle.loop_id),
        ).fetchone()
        if row is None:
            raise AgentStoreError(f"execution={execution_id} 不属于 loop={handle.loop_id}")
        return str(row["status"])

    # ── 交付 ─────────────────────────────────────────────────────

    def start_delivery(self, handle: LoopHandle, delivery_id: str) -> AttemptHandle:
        """发送前预写 sending + attempt 行（§4.2：开始发送的预写状态事务）。"""
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        attempt_id = new_agent_id("att")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._validate_loop_writable(conn, handle)
            row = conn.execute(
                "SELECT status FROM agent_deliveries WHERE delivery_id = ? AND loop_id = ?",
                (delivery_id, handle.loop_id),
            ).fetchone()
            if row is None:
                raise AgentStoreError(f"delivery={delivery_id} 不属于 loop={handle.loop_id}")
            if row["status"] != DeliveryStatus.PLANNED:
                raise LoopNotWritable(f"delivery={delivery_id} 状态 {row['status']} 不允许开始发送")
            index_row = conn.execute(
                "SELECT COALESCE(MAX(attempt_index), -1) + 1 AS next FROM agent_delivery_attempts WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
            attempt_index = int(index_row["next"])
            conn.execute(
                "UPDATE agent_deliveries SET status = ? WHERE delivery_id = ?",
                (DeliveryStatus.SENDING, delivery_id),
            )
            conn.execute(
                """
                INSERT INTO agent_delivery_attempts (attempt_id, delivery_id, attempt_index,
                                                     status, started_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (attempt_id, delivery_id, attempt_index, DeliveryStatus.SENDING, _utc_now()),
            )
            conn.commit()
            return AttemptHandle(
                attempt_id=attempt_id, delivery_id=delivery_id, attempt_index=attempt_index,
            )
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def finish_delivery(self, attempt: AttemptHandle, receipt: DeliveryReceipt) -> None:
        """回执落库（§6.2/§4.2）。

        attempt 终态不被后续尝试覆盖；``unknown`` 收到可信成功回执时允许
        收敛为 ``sent``。目标已删除时只记脱敏诊断日志，不创建新历史。
        Loop 已关闭时的迟到回执提升 replay_revision。
        """
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            attempt_row = conn.execute(
                "SELECT status, finished_at, delivery_id FROM agent_delivery_attempts WHERE attempt_id = ?",
                (attempt.attempt_id,),
            ).fetchone()
            if attempt_row is None:
                logger.warning(
                    "迟到回执指向已删除 attempt=%s delivery=%s（只记诊断，不创建历史）",
                    attempt.attempt_id, attempt.delivery_id,
                )
                conn.rollback()
                return
            delivery_row = conn.execute(
                "SELECT loop_id, status FROM agent_deliveries WHERE delivery_id = ?",
                (attempt_row["delivery_id"],),
            ).fetchone()
            if delivery_row is None:
                logger.warning(
                    "迟到回执指向已删除 delivery=%s（只记诊断，不创建历史）",
                    attempt_row["delivery_id"],
                )
                conn.rollback()
                return
            current = str(attempt_row["status"])
            new_status = receipt.status
            if current in (DeliveryStatus.SENT, DeliveryStatus.FAILED):
                # attempt 终态不可被后续回执覆盖（§4.1），只允许补记 qq id。
                new_status = current
            elif current == DeliveryStatus.UNKNOWN and receipt.status != DeliveryStatus.SENT:
                # unknown 只允许被可信成功回执收敛（§5.5），失败回执不降级。
                new_status = current
            if attempt_row["finished_at"] is None or (
                current == DeliveryStatus.UNKNOWN and new_status == DeliveryStatus.SENT
            ):
                conn.execute(
                    """
                    UPDATE agent_delivery_attempts
                    SET status = ?, finished_at = COALESCE(finished_at, ?),
                        qq_message_id = COALESCE(qq_message_id, ?),
                        error_code = CASE WHEN ? = 'sent' THEN NULL ELSE ? END
                    WHERE attempt_id = ?
                    """,
                    (
                        new_status, _utc_now(),
                        receipt.message_id if new_status == DeliveryStatus.SENT else None,
                        new_status, receipt.error_code, attempt.attempt_id,
                    ),
                )
            loop_row = conn.execute(
                "SELECT closed_at FROM agent_loops WHERE loop_id = ?",
                (delivery_row["loop_id"],),
            ).fetchone()
            if loop_row is not None and loop_row["closed_at"] is not None:
                conn.execute(
                    "UPDATE agent_loops SET replay_revision = replay_revision + 1 WHERE loop_id = ?",
                    (delivery_row["loop_id"],),
                )
            conn.execute(
                "UPDATE agent_deliveries SET status = ? WHERE delivery_id = ? AND status != 'sent'",
                (new_status, attempt_row["delivery_id"]),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def close_loop(
        self, handle: LoopHandle, status: LoopStatus, reason: str | None
    ) -> None:
        """幂等关闭（§4.2/§5.5：基于已提交子项补齐缺失终态后关闭一次）。"""
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT closed_at FROM agent_loops WHERE loop_id = ?", (handle.loop_id,)
            ).fetchone()
            if row is None:
                raise AgentStoreError(f"loop={handle.loop_id} 不存在")
            if row["closed_at"] is not None:
                conn.commit()
                return
            # 收敛在途子项（§5.5）：未开始的交付 skipped、未落库回执 unknown、
            # 声明未启动的工具 not_executed、执行中未落结果的工具 indeterminate
            # （终止原因见 Loop terminal_reason）。
            conn.execute(
                """
                UPDATE agent_tool_executions
                SET status = ?, result_json = COALESCE(result_json, ?),
                    finished_at = COALESCE(finished_at, ?)
                WHERE status = ?
                  AND turn_id IN (SELECT turn_id FROM agent_turns WHERE loop_id = ?)
                """,
                (
                    ToolExecutionStatus.NOT_EXECUTED,
                    self._bounded_result_json(None, ResultRetention.BOUNDED, ToolSkipReason.RECOVERY),
                    _utc_now(), ToolExecutionStatus.DECLARED, handle.loop_id,
                ),
            )
            conn.execute(
                """
                UPDATE agent_tool_executions
                SET status = ?, finished_at = COALESCE(finished_at, ?)
                WHERE status = ?
                  AND turn_id IN (SELECT turn_id FROM agent_turns WHERE loop_id = ?)
                """,
                (ToolExecutionStatus.INDETERMINATE, _utc_now(), ToolExecutionStatus.RUNNING, handle.loop_id),
            )
            conn.execute(
                """
                UPDATE agent_deliveries SET status = ?
                WHERE loop_id = ? AND status = ?
                """,
                (DeliveryStatus.SKIPPED, handle.loop_id, DeliveryStatus.PLANNED),
            )
            conn.execute(
                """
                UPDATE agent_delivery_attempts SET status = ?, finished_at = COALESCE(finished_at, ?)
                WHERE status = ?
                  AND delivery_id IN (SELECT delivery_id FROM agent_deliveries WHERE loop_id = ?)
                """,
                (DeliveryStatus.UNKNOWN, _utc_now(), DeliveryStatus.SENDING, handle.loop_id),
            )
            conn.execute(
                """
                UPDATE agent_deliveries SET status = ?
                WHERE loop_id = ? AND status = ?
                """,
                (DeliveryStatus.UNKNOWN, handle.loop_id, DeliveryStatus.SENDING),
            )
            conn.execute(
                "UPDATE agent_loops SET closed_at = ?, status = ?, terminal_reason = ? WHERE loop_id = ?",
                (_utc_now(), status, reason, handle.loop_id),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _loop_closed(conn: sqlite3.Connection, handle: LoopHandle) -> bool:
        row = conn.execute(
            "SELECT closed_at FROM agent_loops WHERE loop_id = ?", (handle.loop_id,)
        ).fetchone()
        return row is not None and row["closed_at"] is not None

    # ── 读取 ─────────────────────────────────────────────────────

    def load_closed_loops(
        self, scope_key: str, anchor_row_id: int | None = None
    ) -> list[LoadedLoop]:
        """读取完整已关闭 Loop（§8.1：只返回完整 Loop，ASC 全量读）。"""
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        with self._connect() as conn:
            loops = conn.execute(
                """
                SELECT * FROM agent_loops
                WHERE scope_key = ? AND closed_at IS NOT NULL
                  AND (? IS NULL OR anchor_row_id >= ?)
                ORDER BY anchor_row_id ASC
                """,
                (scope_key, anchor_row_id, anchor_row_id),
            ).fetchall()
            result: list[LoadedLoop] = []
            for loop in loops:
                result.append(self._load_one_loop(conn, loop))
        return result

    def _load_one_loop(self, conn: sqlite3.Connection, loop: sqlite3.Row) -> LoadedLoop:
        loop_id = loop["loop_id"]
        user_row: dict[str, Any] = {}
        if loop["anchor_row_id"] is not None:
            anchor = conn.execute(
                """
                SELECT id, user_id, sender_name, canonical_name, role, content,
                       message_id, raw_content, created_at
                FROM conversation_messages WHERE id = ?
                """,
                (loop["anchor_row_id"],),
            ).fetchone()
            if anchor is not None:
                user_row = {key: anchor[key] for key in anchor.keys()}
        turns = conn.execute(
            "SELECT * FROM agent_turns WHERE loop_id = ? ORDER BY turn_index ASC",
            (loop_id,),
        ).fetchall()
        all_deliveries = tuple(
            self._load_one_delivery(conn, row)
            for row in conn.execute(
                "SELECT * FROM agent_deliveries WHERE loop_id = ? ORDER BY delivery_index ASC",
                (loop_id,),
            ).fetchall()
        )
        loaded_turns: list[LoadedTurn] = []
        for turn in turns:
            loaded_tools = tuple(
                LoadedToolExecution(
                    execution_id=row["execution_id"],
                    call_index=int(row["call_index"]),
                    provider_call_id=row["provider_call_id"],
                    tool_name=row["tool_name"],
                    arguments_json=row["arguments_json"],
                    arguments_omission_reason=row["arguments_omission_reason"],
                    status=row["status"],
                    result=json.loads(row["result_json"]) if row["result_json"] else None,
                    result_retention=row["result_retention"],
                    result_omission_reason=row["result_omission_reason"],
                    outbound_media=(
                        json.loads(row["outbound_media_json"])["items"]
                        if row["outbound_media_json"] else []
                    ),
                )
                for row in conn.execute(
                    "SELECT * FROM agent_tool_executions WHERE turn_id = ? ORDER BY call_index ASC",
                    (turn["turn_id"],),
                ).fetchall()
            )
            loaded_deliveries = tuple(
                d for d in all_deliveries if d.turn_id == turn["turn_id"]
            )
            message = conn.execute(
                "SELECT content FROM conversation_messages WHERE id = ?",
                (turn["message_row_id"],),
            ).fetchone()
            loaded_turns.append(
                LoadedTurn(
                    turn_id=turn["turn_id"],
                    turn_index=int(turn["turn_index"]),
                    message_row_id=turn["message_row_id"],
                    text=message["content"] if message is not None else "",
                    parts=tuple(json.loads(turn["parts_json"])["parts"]),
                    native_state=(
                        json.loads(turn["native_state_json"])
                        if turn["native_state_json"] else None
                    ),
                    native_omission_reason=turn["native_omission_reason"],
                    owner=json.loads(turn["owner_json"]) if turn["owner_json"] else None,
                    finish_reason=turn["finish_reason"],
                    text_policy=turn["text_policy"],
                    output_status=turn["output_status"],
                    delivery_policy=turn["delivery_policy"],
                    tools=loaded_tools,
                    deliveries=loaded_deliveries,
                )
            )
        return LoadedLoop(
            loop_id=loop_id,
            scope_key=loop["scope_key"],
            anchor_row_id=int(loop["anchor_row_id"] or 0),
            trigger_kind=loop["trigger_kind"],
            started_at=loop["started_at"],
            closed_at=loop["closed_at"],
            status=loop["status"],
            terminal_reason=loop["terminal_reason"],
            legacy=bool(loop["legacy"]),
            replay_revision=int(loop["replay_revision"]),
            record_bytes=int(loop["record_bytes"]),
            user_row=user_row,
            turns=tuple(loaded_turns),
            deliveries=all_deliveries,
        )

    @staticmethod
    def _load_one_delivery(conn: sqlite3.Connection, row: sqlite3.Row) -> LoadedDelivery:
        qq_ids = [
            r["qq_message_id"]
            for r in conn.execute(
                "SELECT qq_message_id FROM agent_delivery_attempts WHERE delivery_id = ? AND qq_message_id IS NOT NULL",
                (row["delivery_id"],),
            )
        ]
        return LoadedDelivery(
            delivery_id=row["delivery_id"],
            kind=row["kind"],
            turn_id=row["turn_id"],
            tool_execution_id=row["tool_execution_id"],
            chunk_index=row["chunk_index"],
            source_start=row["source_start"],
            source_end=row["source_end"],
            status=row["status"],
            recall_status=row["recall_status"],
            qq_message_ids=tuple(qq_ids),
        )

    def lookup_delivery(self, scope_key: str, qq_message_id: str) -> dict[str, Any] | None:
        """QQ ID → 确切 delivery 溯源（§4.1：必须带 scope 谓词）。"""
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT d.delivery_id, d.loop_id, d.turn_id, d.kind, d.chunk_index,
                       d.source_start, d.source_end, d.status, d.recall_status,
                       a.attempt_id, a.qq_message_id
                FROM agent_delivery_attempts a
                JOIN agent_deliveries d ON d.delivery_id = a.delivery_id
                JOIN agent_loops l ON l.loop_id = d.loop_id
                WHERE l.scope_key = ? AND a.qq_message_id = ?
                ORDER BY a.attempt_index ASC
                LIMIT 1
                """,
                (scope_key, str(qq_message_id)),
            ).fetchone()
        return None if row is None else {key: row[key] for key in row.keys()}

    # ── 恢复与保留 ───────────────────────────────────────────────

    def recover_unfinished_loops(self) -> RecoveryReport:
        """进程崩溃后的恢复（§5.5）：新 Bot 进程执行，幂等。"""
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        closed: list[str] = []
        tools_not_executed: list[str] = []
        tools_indeterminate: list[str] = []
        deliveries_skipped: list[str] = []
        deliveries_unknown: list[str] = []
        with self._connect() as conn:
            loops = conn.execute(
                "SELECT loop_id, scope_key, scope_generation, trigger_kind FROM agent_loops WHERE closed_at IS NULL"
            ).fetchall()
        for loop in loops:
            handle = LoopHandle(
                loop_id=loop["loop_id"],
                scope_key=loop["scope_key"],
                scope_generation=int(loop["scope_generation"]),
                trigger_kind=TriggerKind(loop["trigger_kind"]),
            )
            skipped, unknown = self._recover_one_loop(handle)
            closed.append(handle.loop_id)
            tools_not_executed.extend(skipped["tools"])
            tools_indeterminate.extend(skipped["indeterminate"])
            deliveries_skipped.extend(skipped["deliveries"])
            deliveries_unknown.extend(unknown)
        return RecoveryReport(
            closed_loops=tuple(closed),
            tools_not_executed=tuple(tools_not_executed),
            tools_indeterminate=tuple(tools_indeterminate),
            deliveries_skipped=tuple(deliveries_skipped),
            deliveries_unknown=tuple(deliveries_unknown),
        )

    def _recover_one_loop(
        self, handle: LoopHandle
    ) -> tuple[dict[str, list[str]], list[str]]:
        """§5.5 恢复表的单 Loop 落地：补齐缺失终态后幂等关闭为 interrupted。"""
        tools: list[str] = []
        indeterminate: list[str] = []
        planned_deliveries: list[str] = []
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            declared = conn.execute(
                """
                SELECT e.execution_id FROM agent_tool_executions e
                JOIN agent_turns t ON t.turn_id = e.turn_id
                WHERE t.loop_id = ? AND e.status = ?
                """,
                (handle.loop_id, ToolExecutionStatus.DECLARED),
            ).fetchall()
            for row in declared:
                conn.execute(
                    """
                    UPDATE agent_tool_executions
                    SET status = ?, result_json = COALESCE(result_json, ?), finished_at = COALESCE(finished_at, ?)
                    WHERE execution_id = ?
                    """,
                    (
                        ToolExecutionStatus.NOT_EXECUTED,
                        self._bounded_result_json(None, ResultRetention.BOUNDED, ToolSkipReason.RECOVERY),
                        _utc_now(), row["execution_id"],
                    ),
                )
                tools.append(row["execution_id"])
            running = conn.execute(
                """
                SELECT e.execution_id FROM agent_tool_executions e
                JOIN agent_turns t ON t.turn_id = e.turn_id
                WHERE t.loop_id = ? AND e.status = ?
                """,
                (handle.loop_id, ToolExecutionStatus.RUNNING),
            ).fetchall()
            for row in running:
                conn.execute(
                    "UPDATE agent_tool_executions SET status = ?, finished_at = COALESCE(finished_at, ?) WHERE execution_id = ?",
                    (ToolExecutionStatus.INDETERMINATE, _utc_now(), row["execution_id"]),
                )
                indeterminate.append(row["execution_id"])
            planned_deliveries = [
                row["delivery_id"]
                for row in conn.execute(
                    "SELECT delivery_id FROM agent_deliveries WHERE loop_id = ? AND status = ?",
                    (handle.loop_id, DeliveryStatus.PLANNED),
                ).fetchall()
            ]
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
        # close_loop 收敛 planned→skipped、sending→unknown 并关闭；关闭后
        # 仍为 unknown 的 delivery 即"回执未落库"集合（§5.5 第 3 行）。
        self.close_loop(handle, LoopStatus.INTERRUPTED, "process_recovery")
        unknown = self._sending_delivery_ids(handle.loop_id)
        return (
            {
                "tools": tools,
                "indeterminate": indeterminate,
                "deliveries": planned_deliveries,
            },
            unknown,
        )

    def _sending_delivery_ids(self, loop_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT delivery_id FROM agent_deliveries WHERE loop_id = ? AND status = ?",
                (loop_id, DeliveryStatus.UNKNOWN),
            ).fetchall()
        return [row["delivery_id"] for row in rows]

    def prune_closed_loops(
        self,
        scope_key: str,
        active_anchors: Collection[int],
        policy: RetentionPolicy,
    ) -> PruneReport:
        """D5 保留：按关闭时间/数量/字节清理最旧完整 Loop（§8.4）。

        活动纪元锚点覆盖的 Loop 不清理；硬上限要求越过活动范围时返回
        ``blocked_active_anchors`` 交由调用方推进纪元后重试。
        """
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        active = sorted(int(a) for a in active_anchors)
        floor_anchor = active[0] if active else None
        deleted: list[str] = []
        blocked: list[int] = []
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            now = datetime.now(timezone.utc)
            cutoff_iso = datetime.fromtimestamp(
                now.timestamp() - policy.retention_days * 86400, timezone.utc
            ).isoformat()
            loops = conn.execute(
                """
                SELECT loop_id, anchor_row_id, closed_at, record_bytes FROM agent_loops
                WHERE scope_key = ? AND closed_at IS NOT NULL
                ORDER BY closed_at ASC, anchor_row_id ASC
                """,
                (scope_key,),
            ).fetchall()
            queue = deque(dict(row) for row in loops)
            total_bytes = sum(int(row["record_bytes"]) for row in queue)
            while queue:
                row = queue[0]
                anchor = row["anchor_row_id"]
                if floor_anchor is not None and anchor is not None and anchor >= floor_anchor:
                    # 剩余 Loop 全在活动纪元内；硬上限余量只能靠推进锚点。
                    if len(queue) > policy.max_loops or total_bytes > policy.max_bytes:
                        blocked = [floor_anchor]
                    break
                expired_by_age = str(row["closed_at"]) < cutoff_iso
                over_count = len(queue) > policy.max_loops
                over_bytes = total_bytes > policy.max_bytes
                if not (expired_by_age or over_count or over_bytes):
                    break
                self._delete_whole_loop(conn, row["loop_id"])
                deleted.append(row["loop_id"])
                queue.popleft()
                total_bytes -= int(row["record_bytes"])
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
        return PruneReport(
            deleted_loop_ids=tuple(deleted), blocked_active_anchors=tuple(blocked)
        )

    def suppress_delivery(self, handle: LoopHandle, delivery_id: str) -> None:
        """关闭交付开关时非最终正文的收敛（§6.3：suppressed_by_policy）。"""
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        with self._connect() as conn:
            conn.execute(
                "UPDATE agent_deliveries SET status = ? WHERE delivery_id = ? AND loop_id = ? AND status = ?",
                (DeliveryStatus.SUPPRESSED, delivery_id, handle.loop_id, DeliveryStatus.PLANNED),
            )

    def set_first_chunk_message_id(self, message_row_id: int, qq_message_id: str) -> None:
        """兼容列回填（§4.1）：新 assistant 行取首个确认成功 Chunk 的 ID。"""
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        with self._connect() as conn:
            conn.execute(
                "UPDATE conversation_messages SET message_id = ? WHERE id = ? AND message_id IS NULL",
                (str(qq_message_id), int(message_row_id)),
            )

    def _delete_whole_loop(self, conn: sqlite3.Connection, loop_id: str) -> None:
        """整 Loop 删除（§9.3）：显式按依赖顺序，主表行→Loop（级联侧表）。"""
        conn.execute(
            "DELETE FROM conversation_messages WHERE agent_loop_id = ?", (loop_id,)
        )
        conn.execute("DELETE FROM agent_loops WHERE loop_id = ?", (loop_id,))

    # ── 维护操作（§9 引用、撤回、删除和私聊会话） ──────────────────

    def delete_loops_for_scope(self, scope_key: str) -> int:
        """清空场景的整域删除（§9.3）：全部 Loop 及其主表行，返回删除数。"""
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            loops = [
                row["loop_id"]
                for row in conn.execute(
                    "SELECT loop_id FROM agent_loops WHERE scope_key = ?", (scope_key,)
                )
            ]
            for loop_id in loops:
                self._delete_whole_loop(conn, loop_id)
            conn.commit()
            return len(loops)
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete_loop_by_anchor(self, scope_key: str, anchor_row_id: int) -> bool:
        """按 user 触发行删除整个 Loop（§9.3）。"""
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT loop_id FROM agent_loops WHERE scope_key = ? AND anchor_row_id = ?",
                (scope_key, int(anchor_row_id)),
            ).fetchone()
            if row is None:
                conn.commit()
                return False
            self._delete_whole_loop(conn, row["loop_id"])
            conn.commit()
            return True
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete_turn_by_message_row(self, scope_key: str, message_row_id: int) -> bool:
        """删除一个 Turn 的全部正文范围与交付内容（§9.3）。

        保留协议需要的状态占位：Turn 行与主表行移除，工具声明保留名称与
        终态（结果正文清空），Loop 非公开证据（native/owner）清除。
        """
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            turn = conn.execute(
                """
                SELECT t.turn_id, t.loop_id FROM agent_turns t
                JOIN agent_loops l ON l.loop_id = t.loop_id
                WHERE l.scope_key = ? AND t.message_row_id = ?
                """,
                (scope_key, int(message_row_id)),
            ).fetchone()
            if turn is None:
                conn.commit()
                return False
            conn.execute(
                "DELETE FROM conversation_messages WHERE id = ?", (int(message_row_id),)
            )
            conn.execute(
                "DELETE FROM agent_deliveries WHERE turn_id = ?", (turn["turn_id"],)
            )
            conn.execute(
                """
                UPDATE agent_tool_executions
                SET arguments_json = NULL, arguments_omission_reason = 'recall_cleanup',
                    result_json = NULL, result_omission_reason = 'recall_cleanup',
                    outbound_media_json = NULL
                WHERE turn_id = ?
                """,
                (turn["turn_id"],),
            )
            conn.execute(
                """
                UPDATE agent_turns
                SET native_state_json = NULL, native_omission_reason = 'recall_cleanup',
                    owner_json = NULL, parts_json = ?, text_policy = 'redacted'
                WHERE turn_id = ?
                """,
                (
                    _dumps({"version": AGENT_RECORD_VERSION, "parts": []}),
                    turn["turn_id"],
                ),
            )
            conn.execute(
                "UPDATE agent_loops SET replay_revision = replay_revision + 1 WHERE loop_id = ?",
                (turn["loop_id"],),
            )
            conn.commit()
            return True
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def recall_delivery_chunk(self, scope_key: str, delivery_id: str) -> bool:
        """单 Chunk 撤回（§9.2）：遮蔽源范围并清除该 Loop 的工具/原生证据。

        已确认发送的事实保留（recall_status=recalled）；其余 Chunk 正文
        不动。返回是否命中。
        """
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            delivery = conn.execute(
                """
                SELECT d.delivery_id, d.loop_id, d.turn_id, d.source_start, d.source_end
                FROM agent_deliveries d
                JOIN agent_loops l ON l.loop_id = d.loop_id
                WHERE l.scope_key = ? AND d.delivery_id = ?
                """,
                (scope_key, delivery_id),
            ).fetchone()
            if delivery is None:
                conn.commit()
                return False
            turn_id = delivery["turn_id"]
            turn = conn.execute(
                "SELECT message_row_id FROM agent_turns WHERE turn_id = ?", (turn_id,)
            ).fetchone()
            if turn is not None and turn["message_row_id"] is not None:
                message = conn.execute(
                    "SELECT content FROM conversation_messages WHERE id = ?",
                    (turn["message_row_id"],),
                ).fetchone()
                if message is not None:
                    text = message["content"] or ""
                    start, end = int(delivery["source_start"] or 0), int(delivery["source_end"] or 0)
                    # 等 code point 数遮蔽：保留坐标供后续撤回其他 Chunk。
                    if 0 <= start <= end <= len(text):
                        masked = text[:start] + "▇" * (end - start) + text[end:]
                        conn.execute(
                            "UPDATE conversation_messages SET content = ? WHERE id = ?",
                            (masked, turn["message_row_id"]),
                        )
            conn.execute(
                "UPDATE agent_deliveries SET recall_status = 'recalled' WHERE delivery_id = ?",
                (delivery_id,),
            )
            # 该 Loop 的工具证据与原生状态整体清理（§9.2.3）。
            conn.execute(
                """
                UPDATE agent_tool_executions
                SET arguments_json = NULL, arguments_omission_reason = 'recall_cleanup',
                    result_json = NULL, result_omission_reason = 'recall_cleanup',
                    outbound_media_json = NULL
                WHERE turn_id IN (SELECT turn_id FROM agent_turns WHERE loop_id = ?)
                """,
                (delivery["loop_id"],),
            )
            conn.execute(
                """
                UPDATE agent_turns
                SET native_state_json = NULL, native_omission_reason = 'recall_cleanup',
                    owner_json = NULL
                WHERE loop_id = ?
                """,
                (delivery["loop_id"],),
            )
            conn.execute(
                "UPDATE agent_loops SET replay_revision = replay_revision + 1 WHERE loop_id = ?",
                (delivery["loop_id"],),
            )
            conn.commit()
            return True
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migrate_loops_between_scopes(self, from_scope: str, to_scope: str) -> int:
        """私聊归档/恢复的整 Loop 迁移（§9.4）：ID 与时间不变，双侧 generation 增长。"""
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR IGNORE INTO agent_scopes (scope_key) VALUES (?)", (to_scope,))
            moved = conn.execute(
                "UPDATE agent_loops SET scope_key = ? WHERE scope_key = ?",
                (to_scope, from_scope),
            ).rowcount
            if moved:
                conn.execute(
                    "UPDATE conversation_messages SET group_id = ? WHERE group_id = ?",
                    (to_scope, from_scope),
                )
            for scope in (from_scope, to_scope):
                conn.execute(
                    """
                    UPDATE agent_scopes
                    SET generation = generation + 1, history_revision = history_revision + 1
                    WHERE scope_key = ?
                    """,
                    (scope,),
                )
            conn.commit()
            return int(moved or 0)
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def loops_with_tools(self, scope_key: str, loop_ids: Collection[str]) -> set[str]:
        """判定哪些 Loop 携带工具事实（历史投影替换的门槛，§8.1）。"""
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        if not loop_ids:
            return set()
        with self._connect() as conn:
            placeholders = ",".join("?" for _ in loop_ids)
            rows = conn.execute(
                f"""
                SELECT DISTINCT t.loop_id AS loop_id FROM agent_turns t
                JOIN agent_tool_executions e ON e.turn_id = t.turn_id
                WHERE t.loop_id IN ({placeholders})
                """,
                tuple(loop_ids),
            ).fetchall()
        return {row["loop_id"] for row in rows}

    def load_closed_loops_by_ids(self, scope_key: str, loop_ids: Collection[str]) -> list[LoadedLoop]:
        """按 ID 读取完整已关闭 Loop（历史投影输入；顺序按 anchor ASC）。"""
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        if not loop_ids:
            return []
        with self._connect() as conn:
            placeholders = ",".join("?" for _ in loop_ids)
            loops = conn.execute(
                f"""
                SELECT * FROM agent_loops
                WHERE scope_key = ? AND closed_at IS NOT NULL AND loop_id IN ({placeholders})
                ORDER BY anchor_row_id ASC
                """,
                (scope_key, *loop_ids),
            ).fetchall()
            return [self._load_one_loop(conn, loop) for loop in loops]
