"""会话纪元：固定锚点、冻结历史表达与显式窗口重建。

冷场按空闲时间和可见历史水位缩窗；容量、历史修订和投影配置变化
统一重建纪元。完整 Loop 是裁剪边界，旧会话行沿用 user/assistant 配对。
状态驻留进程内存，重启后按 context_tokens 初始化；事件表提供旁路诊断。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
import uuid
from typing import TYPE_CHECKING

from quickquip.llm.token_estimate import estimate_tokens

if TYPE_CHECKING:
    from quickquip.llm.store import LLMStore
    from quickquip.llm.epoch_history import FrozenHistory

logger = logging.getLogger(__name__)

# 纪元行数裁剪目标；完整的最新 Loop 可超过此值。
DEFAULT_EPOCH_MAX_ROWS = 1024
# 旧式 user/assistant 配对的两轮软下限。
MIN_EPOCH_ROWS = 4
# 每行 speaker 标签渲染开销的估算补偿（`_render_scene_to_text` 的标签约 10~15 token）。
ROW_OVERHEAD_TOKENS = 12


@dataclass(frozen=True, slots=True)
class EpochParams:
    """纪元参数（runtime 全局缺省 + provider 覆盖合并后的生效值）。

    ``context_tokens`` 是标尺参数而非阈值：懒初始化与 ``/llm use`` 新键的
    锚点跨度，并推导 L_cold 的语义基线。
    """

    context_tokens: int = 8000
    cold_idle_seconds: int = 300
    cold_target_tokens: int = 4000
    cold_trigger_tokens: int = 5000
    hot_target_tokens: int = 32000
    cap_tokens: int = 64000


@dataclass(frozen=True, slots=True)
class EpochKey:
    """纪元键：同一 scope 按 (provider, model) 分键，换模型自动开新纪元。"""

    scope_key: str
    provider_id: str
    model: str


@dataclass(slots=True)
class EpochState:
    anchor_id: int
    # 该键最近一次 provider 调用开始或结束的时间，用于空闲判定。
    last_activity_at: float
    id: str = field(default_factory=lambda: create_epoch_id())
    history: FrozenHistory | None = None
    released: bool = False


@dataclass(frozen=True, slots=True)
class EpochResetEvent:
    """一次纪元重建的记录；历史修订可保持原锚点。"""

    reason: str
    old_anchor_id: int
    new_anchor_id: int
    # 重置前的窗口 token 估算（rows/persona 路径未估算时为 -1）。
    epoch_tokens: int = -1


def row_budget(row: dict[str, object]) -> int:
    """单行 history 的预算估算：正文（raw_content 优先）+ 标签开销。

    纪元预算的统一口径：EpochManager 推进判定、usage 计量与 Web 侧窗口
    估算共用，勿在别处另立口径。
    """
    text = str(row.get("raw_content") or row.get("content") or "")
    return estimate_tokens(text) + ROW_OVERHEAD_TOKENS


def estimate_rows_budget(rows: list[dict[str, object]]) -> int:
    """一组 history 行的纪元预算估算（service 计量点与 EpochManager 共用口径）。"""
    return sum(row_budget(row) for row in rows)


class EpochManager:
    """per-(scope, provider, model) 纪元锚点表（进程内，重启即冷一次缓存）。"""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._states: dict[EpochKey, EpochState] = {}

    def maybe_advance(
        self,
        key: EpochKey,
        *,
        store: LLMStore,
        params: EpochParams,
    ) -> EpochResetEvent | None:
        """读取前调用：懒初始化 + 行数兜底 + 冷场/触顶重置判定。

        返回本回合发生的（最后一次）锚点推进事件；未推进返回 None。
        """
        state = self._states.get(key)
        if state is None:
            state = self._lazy_init(key, store, params)
            self._states[key] = state

        event: EpochResetEvent | None = None

        # 行数硬兜底：锚点跨度超 DEFAULT_EPOCH_MAX_ROWS 时先按行数缩，
        # 防海量 1-token 行让 messages 数组爆炸。
        row_anchor = store.find_anchor_row_id_by_rows(key.scope_key, DEFAULT_EPOCH_MAX_ROWS)
        if row_anchor is not None:
            row_anchor = self._pair_align(store, key.scope_key, row_anchor)
        if row_anchor is not None and row_anchor > state.anchor_id:
            event = self._advance(state, store, key, row_anchor, reason="rows")

        rows = store.list_conversation_messages_since(
            key.scope_key, state.anchor_id, limit=None
        )
        total = estimate_rows_budget(rows)
        idle = self._clock() - state.last_activity_at

        if idle > params.cold_idle_seconds and total > params.cold_trigger_tokens:
            # 冷场主动缩回目标水位；实际缓存寿命由渠道决定。
            candidate = self._pair_align(
                store, key.scope_key, self._pick_anchor_by_tokens(rows, params.cold_target_tokens),
            )
            if candidate > state.anchor_id:
                event = self._advance(
                    state, store, key, candidate, reason="cold", epoch_tokens=total
                )
        elif total > params.cap_tokens:
            # 触顶：付费 miss 仅这一次，缩到热水位保住长话题。
            candidate = self._pair_align(
                store, key.scope_key, self._pick_anchor_by_tokens(rows, params.hot_target_tokens),
            )
            if candidate > state.anchor_id:
                event = self._advance(
                    state, store, key, candidate, reason="hot", epoch_tokens=total
                )
        return event

    def frozen_history(self, key: EpochKey) -> FrozenHistory | None:
        state = self._states.get(key)
        return state.history if state else None

    def install_history(self, key: EpochKey, history: FrozenHistory) -> None:
        self._states[key].history = history

    def activate(self, key: EpochKey, *, store: LLMStore) -> None:
        """Keep large projections only for the current model in each scope."""
        for other_key, state in self._states.items():
            if other_key.scope_key == key.scope_key and other_key != key and state.history:
                state.history = None
                state.released = True
        state = self._states.get(key)
        if state is not None and state.released:
            self.rebuild(key, store=store, reason="profile")
            state.released = False

    def rebuild(
        self, key: EpochKey, *, store: LLMStore, reason: str, anchor: int | None = None,
    ) -> EpochResetEvent:
        state = self._states[key]
        return self._advance(
            state, store, key, max(state.anchor_id, anchor or state.anchor_id), reason=reason,
        )

    def advance_scope(self, scope_key: str, anchor: int, *, store: LLMStore, reason: str) -> None:
        for key, state in list(self._states.items()):
            if key.scope_key == scope_key and state.anchor_id < anchor:
                self.rebuild(key, store=store, reason=reason, anchor=anchor)

    def note_activity(self, key: EpochKey, *, epoch_id: str | None = None) -> None:
        """模型调用派发和结束时更新活动；失效请求不能续期新纪元。"""
        state = self._states.get(key)
        if state is not None and (epoch_id is None or state.id == epoch_id):
            state.last_activity_at = self._clock()

    def current_anchor(self, key: EpochKey) -> int | None:
        state = self._states.get(key)
        return state.anchor_id if state is not None else None

    def current_id(self, key: EpochKey) -> str | None:
        state = self._states.get(key)
        return state.id if state is not None else None

    def snapshot(self) -> list[dict[str, object]]:
        """全量锚点状态的值拷贝导出（epoch_snapshot action 消费）。

        只做值拷贝不触发任何判定（不懒初始化、不推进），未初始化的键
        自然缺席——快照语义 = 进程内当前真值，非可能态。
        """
        return [
            {
                "scope_key": key.scope_key,
                "provider_id": key.provider_id,
                "model": key.model,
                "anchor_id": state.anchor_id,
                "last_activity_at": state.last_activity_at,
                "epoch_id": state.id,
                "frozen_segments": state.history.segment_count if state.history else 0,
                "replay_tokens": state.history.replay_tokens if state.history else 0,
            }
            # list() 先把 items 原子快照（C 层循环不释放 GIL）：epoch_snapshot
            # 经 asyncio.to_thread 在 worker 线程执行，迭代期间事件循环线程
            # 增删键不致 RuntimeError
            for key, state in list(self._states.items())
        ]

    def oldest_anchor(self, scope_key: str) -> int | None:
        """该 scope 所有键中最老的锚点（crop 的 floor）；无状态返回 None。"""
        anchors = [
            state.anchor_id
            for key, state in self._states.items()
            if key.scope_key == scope_key
        ]
        return min(anchors) if anchors else None

    def capture_scope_evictions(
        self, scope_key: str, store: "LLMStore",
    ) -> dict[EpochKey, tuple[int, int]]:
        """Observe old-window counts before an atomic history transition."""
        counts = {}
        for key, state in list(self._states.items()):
            if key.scope_key == scope_key:
                try:
                    counts[key] = store.conversation_range_stats(scope_key, state.anchor_id, None)
                except Exception:
                    logger.warning(
                        "epoch eviction snapshot failed scope=%s", scope_key, exc_info=True,
                    )
        return counts

    def reset_scope(
        self, scope_key: str, *, store: "LLMStore | None" = None,
        evictions: dict[EpochKey, tuple[int, int]] | None = None,
    ) -> None:
        """clear_context 第三清：抹掉该 scope 的全部纪元键。

        带 store 时逐键落 ``reason='clear'`` 事件（new_anchor_id = NULL 表
        示锚点已抹除）；事件失败只告警，绝不阻断清键。
        """
        doomed = [key for key in self._states if key.scope_key == scope_key]
        for key in doomed:
            if store is not None:
                self._record_event(
                    store, key, "clear", self._states[key].anchor_id, None,
                    evicted_stats=evictions.get(key, (0, 0)) if evictions is not None else None,
                )
            del self._states[key]

    def advance_to_cold_water(
        self,
        key: EpochKey,
        *,
        store: LLMStore,
        params: EpochParams,
        reason: str = "persona",
    ) -> EpochResetEvent | None:
        """persona 切换挂钩：system 字节变化 = 该键缓存全灭 = 免费重置窗口，
        按冷场水位（H_cold/L_cold）挪锚点；不看 idle。低于水位不动。
        """
        state = self._states.get(key)
        if state is None:
            state = self._lazy_init(key, store, params)
            self._states[key] = state
        rows = store.list_conversation_messages_since(
            key.scope_key, state.anchor_id, limit=None
        )
        total = estimate_rows_budget(rows)
        event: EpochResetEvent | None = None
        if total > params.cold_trigger_tokens:
            candidate = self._pair_align(
                store, key.scope_key, self._pick_anchor_by_tokens(rows, params.cold_target_tokens),
            )
            if candidate > state.anchor_id:
                event = self._advance(
                    state, store, key, candidate, reason=reason, epoch_tokens=total
                )
        # persona 切换后缓存重新烧入，T 从切换点重新计。
        state.last_activity_at = self._clock()
        return event

    def force_advance_to_hot(
        self,
        key: EpochKey,
        *,
        store: LLMStore,
        params: EpochParams,
    ) -> EpochResetEvent | None:
        """容量 reset 路径（§8.3）：请求预算超限时的付费降级。

        不看 idle 与 cap 触发条件，直接把锚点缩到热水位（L_hot）；与
        ``maybe_advance`` 同款行数兜底先行（窗口行数超限时先按行数推进，
        绝不让范围读截掉最新端）。无状态（本进程未见过该键）或已无更小
        锚点时返回 None，由调用方走终止路径；仅行数兜底推进时返回该事件。
        """
        state = self._states.get(key)
        if state is None:
            return None
        event: EpochResetEvent | None = None
        row_anchor = store.find_anchor_row_id_by_rows(key.scope_key, DEFAULT_EPOCH_MAX_ROWS)
        if row_anchor is not None:
            row_anchor = self._pair_align(store, key.scope_key, row_anchor)
        if row_anchor is not None and row_anchor > state.anchor_id:
            event = self._advance(state, store, key, row_anchor, reason="rows")
        rows = store.list_conversation_messages_since(
            key.scope_key, state.anchor_id, limit=None
        )
        candidate = self._pair_align(
            store, key.scope_key, self._pick_anchor_by_tokens(rows, params.hot_target_tokens),
        )
        if candidate > state.anchor_id:
            return self._advance(
                state, store, key, candidate, reason="hot", epoch_tokens=estimate_rows_budget(rows)
            )
        return event

    # ── 内部 ─────────────────────────────────────────────────────

    def _lazy_init(self, key: EpochKey, store: LLMStore, params: EpochParams) -> EpochState:
        """懒初始化：锚点 = 距 head 标准 CTX 跨度（pair 对齐），不从空纪元起步。

        覆盖两种场景：部署初始化（既有 scope 首跑）与 ``/llm use`` 新键——
        新模型首轮缓存本冷，预热顺带烧入宽上下文，不附带截肢。活动时间记为
        初始化时刻，避免首轮立即触发冷场重置把宽上下文裁掉。

        读集先锚到最新 ``DEFAULT_EPOCH_MAX_ROWS`` 行的起点再读——直接
        ``ASC + LIMIT`` 会读到最旧一批行，CTX 跨度就量在了错误的一端。
        """
        start = store.find_anchor_row_id_by_rows(key.scope_key, DEFAULT_EPOCH_MAX_ROWS) or 0
        start = self._pair_align(store, key.scope_key, start)
        rows = store.list_conversation_messages_since(
            key.scope_key, start, limit=None
        )
        anchor = 0
        if rows:
            anchor = self._pair_align(
                store, key.scope_key, self._pick_anchor_by_tokens(rows, params.context_tokens)
            )
        self._record_event(store, key, "init", 0, anchor)
        return EpochState(anchor_id=anchor, last_activity_at=self._clock())

    def _advance(
        self,
        state: EpochState,
        store: "LLMStore",
        key: EpochKey,
        candidate_anchor: int,
        *,
        reason: str,
        epoch_tokens: int = -1,
    ) -> EpochResetEvent:
        old_anchor = state.anchor_id
        state.anchor_id = self._pair_align(store, key.scope_key, candidate_anchor)
        state.id = create_epoch_id()
        state.history = None
        logger.info(
            "epoch advance scope=%s provider=%s model=%s reason=%s anchor=%d->%d tokens=%d",
            key.scope_key,
            key.provider_id,
            key.model,
            reason,
            old_anchor,
            state.anchor_id,
            epoch_tokens,
        )
        self._record_event(store, key, reason, old_anchor, state.anchor_id, epoch_tokens)
        return EpochResetEvent(
            reason=reason,
            old_anchor_id=old_anchor,
            new_anchor_id=state.anchor_id,
            epoch_tokens=epoch_tokens,
        )

    def _record_event(
        self,
        store: "LLMStore",
        key: EpochKey,
        reason: str,
        old_anchor_id: int,
        new_anchor_id: int | None,
        epoch_tokens: int = -1,
        evicted_stats: tuple[int, int] | None = None,
    ) -> None:
        """锚点推进的旁路落库（epoch_events 表）：失败只告警，绝不阻断主链路。"""
        try:
            evicted_rows, evicted_tokens = evicted_stats or store.conversation_range_stats(
                key.scope_key, old_anchor_id, new_anchor_id
            )
            store.record_epoch_event(
                scope_key=key.scope_key,
                provider_id=key.provider_id,
                model=key.model,
                reason=reason,
                old_anchor_id=old_anchor_id,
                new_anchor_id=new_anchor_id,
                epoch_tokens=epoch_tokens,
                evicted_rows=evicted_rows,
                evicted_tokens=evicted_tokens,
            )
        except Exception:
            logger.warning(
                "epoch event persist failed scope=%s provider=%s model=%s reason=%s",
                key.scope_key,
                key.provider_id,
                key.model,
                reason,
                exc_info=True,
            )

    def _pair_align(self, store: LLMStore, scope_key: str, anchor_id: int) -> int:
        """对齐完整 Loop 或旧式 user/assistant 配对边界。"""
        return store.align_history_anchor(scope_key, anchor_id)

    @staticmethod
    def _pick_anchor_by_tokens(rows: list[dict[str, object]], target_tokens: int) -> int:
        """从最新消息向旧累加到目标预算，至少选择两个完整历史单元。"""
        if not rows:
            return 0
        total = 0
        idx = len(rows)
        while idx > 0:
            idx -= 1
            total += row_budget(rows[idx])
            if total >= target_tokens:
                break
        from quickquip.llm.epoch_history import history_units

        units = history_units(rows)
        soft_floor = int(units[max(0, len(units) - 2)][0]["id"])
        floor_index = next(i for i, row in enumerate(rows) if int(row["id"]) == soft_floor)
        idx = min(idx, floor_index)
        return int(rows[idx]["id"])


def create_epoch_id() -> str:
    """Temporary operations and chat windows use distinct UUIDv4 epoch identities."""
    return str(uuid.uuid4())
