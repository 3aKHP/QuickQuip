"""会话纪元（session epoch）：history 读取的只追加窗口机制。

设计要点（权威设计见私有计划文档 §4，本模块为落地实现）：

- 窗口单位从「行数滚动窗」（``ORDER BY id DESC LIMIT N``，每轮首条位移、
  前缀缓存结构性失效）改为 ``id >= anchor_id`` 的只追加纪元窗——纪元内
  前缀逐字节稳定。
- 锚点状态是**进程内字典**（本模块的 ``EpochManager._states``），不落库：
  进程重启 = 冷一次缓存，重启后首个请求按「距 head 标准 CTX 跨度」懒初始化。
- 重置时机只绑两件事：缓存已冷（距上次 LLM 请求 > T 且窗口 > H_cold，免费
  miss，缩到 L_cold）或触顶（窗口 > cap，付费 miss 一次，缩到 L_hot）。
- 逐出原子性：锚点只落在 user/assistant 对边界（user 行），``MIN_EPOCH_ROWS``
  保护防单条超长转发吃空下限。
- 预算单位是 token（``token_estimate.estimate_tokens``），每行加
  ``ROW_OVERHEAD_TOKENS`` 的 speaker 标签渲染开销，以 usage 实际值持续校准。
- ``DEFAULT_EPOCH_MAX_ROWS`` 行数硬兜底：防海量 1-token 行撑爆 provider 侧
  messages 数组；行数约束一律转化为锚点推进，绝不对范围读直接 LIMIT 截断
  （ASC + LIMIT 会截掉最新行——错误的一端）。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from quickquip.llm.token_estimate import estimate_tokens

if TYPE_CHECKING:
    from quickquip.llm.store import LLMStore

logger = logging.getLogger(__name__)

# 纪元读取的行数硬兜底（防海量 1-token 行撑爆 messages 数组）。
DEFAULT_EPOCH_MAX_ROWS = 1024
# 锚点推进时保留的最少行数（防单条超长转发吃空下限）。
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
    # 该键最近一次 LLM 请求派发的时间（不是群内最近消息）——只有请求才续期
    # provider 侧缓存。
    last_activity_at: float


@dataclass(frozen=True, slots=True)
class EpochResetEvent:
    """一次锚点推进的记录（reason ∈ cold / hot / rows / persona）。"""

    reason: str
    old_anchor_id: int
    new_anchor_id: int
    # 重置前的窗口 token 估算（rows/persona 路径未估算时为 -1）。
    epoch_tokens: int = -1


def _row_budget(row: dict[str, object]) -> int:
    """单行 history 的预算估算：正文（raw_content 优先）+ 标签开销。"""
    text = str(row.get("raw_content") or row.get("content") or "")
    return estimate_tokens(text) + ROW_OVERHEAD_TOKENS


def estimate_rows_budget(rows: list[dict[str, object]]) -> int:
    """一组 history 行的纪元预算估算（service 计量点与 EpochManager 共用口径）。"""
    return sum(_row_budget(row) for row in rows)


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
        if row_anchor is not None and row_anchor > state.anchor_id:
            event = self._advance(state, store, key, row_anchor, reason="rows")

        rows = store.list_conversation_messages_since(
            key.scope_key, state.anchor_id, limit=DEFAULT_EPOCH_MAX_ROWS
        )
        total = estimate_rows_budget(rows)
        idle = self._clock() - state.last_activity_at

        if idle > params.cold_idle_seconds and total > params.cold_trigger_tokens:
            # 冷场：provider 侧缓存已死，重置是免费 miss，缩回冷场水位。
            candidate = self._pick_anchor_by_tokens(rows, params.cold_target_tokens)
            if candidate > state.anchor_id:
                event = self._advance(state, store, key, candidate, reason="cold", epoch_tokens=total)
        elif total > params.cap_tokens:
            # 触顶：付费 miss 仅这一次，缩到热水位保住长话题。
            candidate = self._pick_anchor_by_tokens(rows, params.hot_target_tokens)
            if candidate > state.anchor_id:
                event = self._advance(state, store, key, candidate, reason="hot", epoch_tokens=total)
        return event

    def note_activity(self, key: EpochKey) -> None:
        """请求派发前调用：续期该键的活动时间（失败请求也可能已写缓存，保守续期）。"""
        state = self._states.get(key)
        if state is not None:
            state.last_activity_at = self._clock()

    def current_anchor(self, key: EpochKey) -> int | None:
        state = self._states.get(key)
        return state.anchor_id if state is not None else None

    def oldest_anchor(self, scope_key: str) -> int | None:
        """该 scope 所有键中最老的锚点（crop 的 floor）；无状态返回 None。"""
        anchors = [state.anchor_id for key, state in self._states.items() if key.scope_key == scope_key]
        return min(anchors) if anchors else None

    def reset_scope(self, scope_key: str) -> None:
        """clear_context 第三清：抹掉该 scope 的全部纪元键。"""
        doomed = [key for key in self._states if key.scope_key == scope_key]
        for key in doomed:
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
            key.scope_key, state.anchor_id, limit=DEFAULT_EPOCH_MAX_ROWS
        )
        total = estimate_rows_budget(rows)
        event: EpochResetEvent | None = None
        if total > params.cold_trigger_tokens:
            candidate = self._pick_anchor_by_tokens(rows, params.cold_target_tokens)
            if candidate > state.anchor_id:
                event = self._advance(state, store, key, candidate, reason=reason, epoch_tokens=total)
        # persona 切换后缓存重新烧入，T 从切换点重新计。
        state.last_activity_at = self._clock()
        return event

    # ── 内部 ─────────────────────────────────────────────────────

    def _lazy_init(self, key: EpochKey, store: LLMStore, params: EpochParams) -> EpochState:
        """懒初始化：锚点 = 距 head 标准 CTX 跨度（pair 对齐），不从空纪元起步。

        覆盖两种场景：部署初始化（既有 scope 首跑）与 ``/llm use`` 新键——
        新模型首轮缓存本冷，预热顺带烧入宽上下文，不附带截肢。活动时间记为
        初始化时刻，避免首轮立即触发冷场重置把宽上下文裁掉。
        """
        rows = store.list_conversation_messages_since(key.scope_key, 0, limit=DEFAULT_EPOCH_MAX_ROWS)
        anchor = 0
        if rows:
            anchor = self._pair_align(store, key.scope_key, self._pick_anchor_by_tokens(rows, params.context_tokens))
        return EpochState(anchor_id=anchor, last_activity_at=self._clock())

    def _advance(
        self,
        state: EpochState,
        store: LLMStore,
        key: EpochKey,
        candidate_anchor: int,
        *,
        reason: str,
        epoch_tokens: int = -1,
    ) -> EpochResetEvent:
        old_anchor = state.anchor_id
        state.anchor_id = self._pair_align(store, key.scope_key, candidate_anchor)
        logger.info(
            "epoch advance scope=%s provider=%s model=%s reason=%s anchor=%d->%d tokens=%d",
            key.scope_key, key.provider_id, key.model, reason, old_anchor, state.anchor_id, epoch_tokens,
        )
        return EpochResetEvent(
            reason=reason,
            old_anchor_id=old_anchor,
            new_anchor_id=state.anchor_id,
            epoch_tokens=epoch_tokens,
        )

    def _pair_align(self, store: LLMStore, scope_key: str, anchor_id: int) -> int:
        """锚点只落在 user/assistant 对边界：对齐到 >= anchor 的首条 user 行。"""
        next_user = store.find_next_user_row_id(scope_key, anchor_id)
        return next_user if next_user is not None else anchor_id

    @staticmethod
    def _pick_anchor_by_tokens(rows: list[dict[str, object]], target_tokens: int) -> int:
        """从 head 向旧累加预算到 >= target，返回锚点候选行 id（含 MIN_EPOCH_ROWS 保护）。"""
        if not rows:
            return 0
        total = 0
        idx = len(rows)
        while idx > 0:
            idx -= 1
            total += _row_budget(rows[idx])
            if total >= target_tokens:
                break
        # MIN_EPOCH_ROWS 保护：单条超长行（如大转发）不得把窗口吃空到不足 4 行。
        idx = min(idx, max(0, len(rows) - MIN_EPOCH_ROWS))
        return int(rows[idx]["id"])
