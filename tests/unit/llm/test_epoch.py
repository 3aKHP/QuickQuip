"""会话纪元（epoch.py）单元测试。

覆盖：懒初始化 CTX 跨度锚定、冷场/触顶/行数兜底三种锚点推进、pair 边界与
MIN_EPOCH_ROWS 保护、reset_scope / persona 挪锚 / note_activity 续期语义。
测试用小参数组（百级 token）放大行为差异，定标默认值由
test_params_defaults_match_calibration 单独钉死。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quickquip.llm.epoch import (
    DEFAULT_EPOCH_MAX_ROWS,
    MIN_EPOCH_ROWS,
    EpochKey,
    EpochManager,
    EpochParams,
    estimate_rows_budget,
)
from quickquip.llm.store import LLMStore


@pytest.fixture
def store(tmp_path: Path) -> LLMStore:
    return LLMStore(tmp_path / "epoch_test.db")


class FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _seed_pairs(store: LLMStore, scope: str, pairs: int, chars: int = 10) -> None:
    text = "字" * chars
    for i in range(pairs):
        store.append_conversation_message(scope, "u", "user", f"问{i}{text}")
        store.append_conversation_message(scope, None, "assistant", f"答{i}{text}")


def _rows_since(store: LLMStore, scope: str, anchor: int) -> list[dict[str, object]]:
    return store.list_conversation_messages_since(scope, anchor, limit=DEFAULT_EPOCH_MAX_ROWS + 100)


_KEY = EpochKey(scope_key="1001", provider_id="p1", model="m1")
# 小参数组：20 行（10 对，每行约 21 token）下，懒初始化窗口 ≈200 > 触发水位 150，
# 暖轮靠 idle 闸防重置，冷场缩到 100，触顶（>500）缩到 400。
_SMALL = EpochParams(
    context_tokens=200,
    cold_idle_seconds=300,
    cold_target_tokens=100,
    cold_trigger_tokens=150,
    hot_target_tokens=400,
    cap_tokens=500,
)


def test_params_defaults_match_calibration() -> None:
    params = EpochParams()
    assert params.context_tokens == 8000
    assert params.cold_idle_seconds == 300
    assert params.cold_target_tokens == 4000
    assert params.cold_trigger_tokens == 5000
    assert params.hot_target_tokens == 32000
    assert params.cap_tokens == 64000


def test_lazy_init_empty_store(store: LLMStore) -> None:
    mgr = EpochManager(clock=FakeClock())
    event = mgr.maybe_advance(_KEY, store=store, params=_SMALL)
    assert event is None
    assert mgr.current_anchor(_KEY) == 0


def test_lazy_init_anchor_spans_context_tokens(store: LLMStore) -> None:
    _seed_pairs(store, "1001", 10)
    mgr = EpochManager(clock=FakeClock())
    event = mgr.maybe_advance(_KEY, store=store, params=_SMALL)

    assert event is None  # 懒初始化本身不算重置事件
    anchor = mgr.current_anchor(_KEY)
    assert anchor is not None and anchor > 0  # 不从空纪元起步
    rows = _rows_since(store, "1001", anchor)
    assert rows[0]["role"] == "user"  # pair 边界
    budget = estimate_rows_budget(rows)
    # 跨度 ≈ CTX（pair 对齐前移最多损失两行预算）
    assert budget <= _SMALL.context_tokens + 2 * 25
    assert budget >= _SMALL.context_tokens - 2 * 25
    assert len(rows) < 20  # 确实有裁剪


def test_warm_turn_no_reset(store: LLMStore) -> None:
    _seed_pairs(store, "1001", 10)
    clock = FakeClock()
    mgr = EpochManager(clock=clock)
    mgr.maybe_advance(_KEY, store=store, params=_SMALL)
    anchor = mgr.current_anchor(_KEY)
    # 窗口 > H_cold 但 idle < T：暖轮绝不重置（前缀稳定性 > 预算）
    event = mgr.maybe_advance(_KEY, store=store, params=_SMALL)
    assert event is None
    assert mgr.current_anchor(_KEY) == anchor


def test_cold_reset_shrinks_to_cold_target(store: LLMStore) -> None:
    _seed_pairs(store, "1001", 10)
    clock = FakeClock()
    mgr = EpochManager(clock=clock)
    mgr.maybe_advance(_KEY, store=store, params=_SMALL)
    old_anchor = mgr.current_anchor(_KEY)

    clock.advance(301)
    event = mgr.maybe_advance(_KEY, store=store, params=_SMALL)

    assert event is not None and event.reason == "cold"
    assert event.new_anchor_id > old_anchor
    rows = _rows_since(store, "1001", event.new_anchor_id)
    assert rows[0]["role"] == "user"
    assert estimate_rows_budget(rows) <= _SMALL.cold_target_tokens + 2 * 25


def test_cold_reset_skipped_below_trigger(store: LLMStore) -> None:
    _seed_pairs(store, "1001", 3)  # ≈126 token，低于 H_cold=150
    clock = FakeClock()
    mgr = EpochManager(clock=clock)
    mgr.maybe_advance(_KEY, store=store, params=_SMALL)
    anchor = mgr.current_anchor(_KEY)

    clock.advance(301)
    event = mgr.maybe_advance(_KEY, store=store, params=_SMALL)
    assert event is None
    assert mgr.current_anchor(_KEY) == anchor


def test_hot_reset_shrinks_to_hot_target(store: LLMStore) -> None:
    _seed_pairs(store, "1001", 20)  # 40 行 ≈840 token
    params = EpochParams(
        context_tokens=10000,  # 懒初始化保留全量，直接把窗口推过 cap
        cold_idle_seconds=300,
        cold_target_tokens=100,
        cold_trigger_tokens=150,
        hot_target_tokens=400,
        cap_tokens=500,
    )
    mgr = EpochManager(clock=FakeClock())
    event = mgr.maybe_advance(_KEY, store=store, params=params)

    assert event is not None and event.reason == "hot"
    rows = _rows_since(store, "1001", event.new_anchor_id)
    assert rows[0]["role"] == "user"
    assert estimate_rows_budget(rows) <= params.hot_target_tokens + 2 * 25


def test_anchor_pair_boundary_and_min_rows(store: LLMStore) -> None:
    _seed_pairs(store, "1001", 2)
    big = "字" * 2000  # 单条 ≈1400 token 的超长行（大转发形态）
    store.append_conversation_message("1001", "u", "user", big)
    store.append_conversation_message("1001", None, "assistant", "答")
    params = EpochParams(
        context_tokens=10000,
        cold_idle_seconds=300,
        cold_target_tokens=100,
        cold_trigger_tokens=150,
        hot_target_tokens=400,
        cap_tokens=50000,
    )
    clock = FakeClock()
    mgr = EpochManager(clock=clock)
    mgr.maybe_advance(_KEY, store=store, params=params)

    clock.advance(301)
    event = mgr.maybe_advance(_KEY, store=store, params=params)

    assert event is not None and event.reason == "cold"
    rows = _rows_since(store, "1001", event.new_anchor_id)
    # 单条超长行不得把窗口吃空到不足 MIN_EPOCH_ROWS
    assert len(rows) >= MIN_EPOCH_ROWS
    assert rows[0]["role"] == "user"


def test_lazy_init_measures_ctx_span_from_true_head(store: LLMStore) -> None:
    """回归：scope 行数 > DEFAULT_EPOCH_MAX_ROWS 时，CTX 跨度也必须从真 head
    起量（曾误读最旧 1024 行，锚点量在第 1024 行处，窗口被放大到 1024 行）。"""
    _seed_pairs(store, "1001", 600, chars=1)  # 1200 行
    mgr = EpochManager(clock=FakeClock())
    mgr.maybe_advance(_KEY, store=store, params=_SMALL)  # CTX=200

    anchor = mgr.current_anchor(_KEY)
    rows = _rows_since(store, "1001", anchor)
    assert rows[0]["role"] == "user"
    assert estimate_rows_budget(rows) <= _SMALL.context_tokens + 2 * 25
    # 真 head 起量：≈200 token ≈ 十几行量级；错误读集下会膨胀到 ~1024 行
    assert len(rows) <= 30


def test_row_backstop_advances_anchor(store: LLMStore) -> None:
    """纪元窗口随回合增长超过行数硬兜底时锚点必须推进（而非 LIMIT 截最新端）。"""
    _seed_pairs(store, "1001", 20, chars=1)
    params = EpochParams(
        context_tokens=200000,  # 懒初始化保留全量（锚在第一行）
        cold_idle_seconds=300,
        cold_target_tokens=100000,
        cold_trigger_tokens=150000,
        hot_target_tokens=180000,
        cap_tokens=190000,
    )
    mgr = EpochManager(clock=FakeClock())
    mgr.maybe_advance(_KEY, store=store, params=params)
    old_anchor = mgr.current_anchor(_KEY)

    _seed_pairs(store, "1001", 560, chars=1)  # 再长 1120 行，总量 1160 > 1024
    event = mgr.maybe_advance(_KEY, store=store, params=params)

    assert event is not None and event.reason == "rows"
    anchor = mgr.current_anchor(_KEY)
    assert anchor > old_anchor
    rows = _rows_since(store, "1001", anchor)
    assert len(rows) <= DEFAULT_EPOCH_MAX_ROWS
    assert rows[0]["role"] == "user"  # 行数兜底同样 pair 对齐


def test_reset_scope_clears_all_keys(store: LLMStore) -> None:
    _seed_pairs(store, "1001", 5)
    _seed_pairs(store, "2002", 5)
    mgr = EpochManager(clock=FakeClock())
    key_a = EpochKey(scope_key="1001", provider_id="p1", model="m1")
    key_b = EpochKey(scope_key="1001", provider_id="p2", model="m2")
    key_c = EpochKey(scope_key="2002", provider_id="p1", model="m1")
    for key in (key_a, key_b, key_c):
        mgr.maybe_advance(key, store=store, params=_SMALL)

    mgr.reset_scope("1001")

    assert mgr.current_anchor(key_a) is None
    assert mgr.current_anchor(key_b) is None
    assert mgr.current_anchor(key_c) is not None
    assert mgr.oldest_anchor("1001") is None
    assert mgr.oldest_anchor("2002") is not None


def test_persona_advance_ignores_idle(store: LLMStore) -> None:
    _seed_pairs(store, "1001", 10)
    mgr = EpochManager(clock=FakeClock())
    mgr.maybe_advance(_KEY, store=store, params=_SMALL)
    old_anchor = mgr.current_anchor(_KEY)

    # idle ≈ 0（暖轮），persona 切换仍按冷场水位挪锚——缓存全灭是免费重置窗口
    event = mgr.advance_to_cold_water(_KEY, store=store, params=_SMALL)

    assert event is not None and event.reason == "persona"
    assert event.new_anchor_id > old_anchor
    rows = _rows_since(store, "1001", event.new_anchor_id)
    assert estimate_rows_budget(rows) <= _SMALL.cold_target_tokens + 2 * 25


def test_note_activity_refreshes_timestamp(store: LLMStore) -> None:
    _seed_pairs(store, "1001", 10)
    clock = FakeClock()
    mgr = EpochManager(clock=clock)
    mgr.maybe_advance(_KEY, store=store, params=_SMALL)

    clock.advance(200)
    mgr.note_activity(_KEY)
    clock.advance(200)  # 距初始化 400s > T，但距最近请求仅 200s < T
    event = mgr.maybe_advance(_KEY, store=store, params=_SMALL)
    assert event is None

    clock.advance(150)  # 距最近请求 350s > T
    event = mgr.maybe_advance(_KEY, store=store, params=_SMALL)
    assert event is not None and event.reason == "cold"


def test_oldest_anchor_returns_min_across_keys(store: LLMStore) -> None:
    _seed_pairs(store, "1001", 10)
    clock = FakeClock()
    mgr = EpochManager(clock=clock)
    key_a = EpochKey(scope_key="1001", provider_id="p1", model="m1")
    key_b = EpochKey(scope_key="1001", provider_id="p2", model="m2")
    mgr.maybe_advance(key_a, store=store, params=_SMALL)
    clock.advance(301)
    mgr.maybe_advance(key_a, store=store, params=_SMALL)  # key_a 冷场前移
    mgr.maybe_advance(key_b, store=store, params=_SMALL)  # key_b 后初始化，锚点更靠后

    oldest = mgr.oldest_anchor("1001")
    assert oldest == min(mgr.current_anchor(key_a), mgr.current_anchor(key_b))
    # key_a 冷场缩窗后锚点更新（id 更大），key_b 窗口更大锚点更老
    assert mgr.current_anchor(key_a) > mgr.current_anchor(key_b)
    assert oldest == mgr.current_anchor(key_b)
