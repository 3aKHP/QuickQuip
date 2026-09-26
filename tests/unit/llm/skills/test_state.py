"""per-会话激活状态（state.SkillActivationState）。"""
from __future__ import annotations

from quickquip.llm.skills import SkillActivationState


def test_duplicate_only_for_same_scope_name_hash():
    state = SkillActivationState()
    assert not state.is_duplicate("s1", "demo", "h1")
    state.record("s1", "demo", "h1")
    assert state.is_duplicate("s1", "demo", "h1")
    # hash 变更 → 不是重复，需要重新注入
    assert not state.is_duplicate("s1", "demo", "h2")
    # 其他 scope / 其他 name 不受影响
    assert not state.is_duplicate("s2", "demo", "h1")
    assert not state.is_duplicate("s1", "other", "h1")


def test_record_overwrites_hash():
    state = SkillActivationState()
    state.record("s1", "demo", "h1")
    state.record("s1", "demo", "h2")
    assert state.is_duplicate("s1", "demo", "h2")
    assert not state.is_duplicate("s1", "demo", "h1")


def test_is_active_and_activated_names_scope_isolated():
    state = SkillActivationState()
    assert not state.is_active("s1", "demo")
    state.record("s1", "beta", "h")
    state.record("s1", "alpha", "h")
    state.record("s2", "gamma", "h")
    assert state.is_active("s1", "alpha")
    assert not state.is_active("s1", "gamma")
    assert state.activated_names("s1") == ["alpha", "beta"]
    assert state.activated_names("s2") == ["gamma"]
    assert state.activated_names("s3") == []


def test_clear_scope_removes_only_that_scope():
    state = SkillActivationState()
    state.record("s1", "alpha", "h")
    state.record("s1", "beta", "h")
    state.record("s2", "gamma", "h")
    state.clear_scope("s1")
    assert state.activated_names("s1") == []
    assert state.is_active("s2", "gamma")
    # 清过的 scope 可重新登记
    state.record("s1", "alpha", "h2")
    assert state.is_active("s1", "alpha")


def test_drop_outdated_clears_only_out_of_window():
    """窗口守卫:登记尾部早于生效锚点才清;未知尾部与在窗登记保留。"""
    state = SkillActivationState()
    state.record("s", "a", "h1", tail_row_id=10)
    state.record("s", "b", "h2", tail_row_id=20)
    state.record("s", "c", "h3")  # 尾部未知(旧登记形态),不参与巡检
    state.drop_outdated("s", anchor_row_id=15)
    assert not state.is_active("s", "a")
    assert state.is_active("s", "b")
    assert state.is_active("s", "c")
    state.drop_outdated("other", 999)  # 其他 scope 不受影响
    assert state.is_active("s", "b")
