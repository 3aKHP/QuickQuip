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
