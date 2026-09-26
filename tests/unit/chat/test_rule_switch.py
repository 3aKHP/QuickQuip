from __future__ import annotations

from pathlib import Path

import pytest

from quickquip.chat import rule_switch
from quickquip.chat.rule_switch import GroupRuleSwitch


@pytest.fixture(autouse=True)
def synthetic_rule_names(monkeypatch):
    monkeypatch.setattr(rule_switch, "SWITCHABLE_RULES", {"rule_a", "rule_b", "rule_c"})


def test_defaults_to_enabled():
    s = GroupRuleSwitch()
    assert s.is_enabled(7001, "rule_a") is True


def test_disable_and_enable():
    s = GroupRuleSwitch()
    assert s.disable(7001, "rule_a") is True
    assert s.is_enabled(7001, "rule_a") is False
    assert s.enable(7001, "rule_a") is True
    assert s.is_enabled(7001, "rule_a") is True


def test_disable_unknown_rule_returns_false():
    s = GroupRuleSwitch()
    assert s.disable(7001, "not_a_rule") is False


def test_group_isolation():
    s = GroupRuleSwitch()
    s.disable(7001, "rule_b")
    assert s.is_enabled(7001, "rule_b") is False
    assert s.is_enabled(7002, "rule_b") is True


def test_list_disabled():
    s = GroupRuleSwitch()
    s.disable(7001, "rule_b")
    s.disable(7001, "rule_c")
    disabled = s.list_disabled(7001)
    assert "rule_b" in disabled
    assert "rule_c" in disabled


def test_format_shows_on_off_markers():
    s = GroupRuleSwitch()
    s.disable(7001, "rule_b")
    out = s.format_rules(7001)
    assert "[OFF] rule_b" in out
    assert "[ON] rule_a" in out


def test_lru_eviction():
    s = GroupRuleSwitch(max_groups=2)
    s.disable(1, "rule_a")
    s.disable(2, "rule_a")
    s.disable(3, "rule_a")
    assert list(s.disabled.keys()) == ["2", "3"]


def test_dict_roundtrip():
    s = GroupRuleSwitch()
    s.disable(7001, "rule_a")
    s.disable(7001, "rule_b")
    s.disable(7002, "rule_c")
    snapshot = s.to_dict()
    restored = GroupRuleSwitch()
    restored.from_dict(snapshot)
    assert restored.is_enabled(7001, "rule_a") is False
    assert restored.is_enabled(7001, "rule_b") is False
    assert restored.is_enabled(7002, "rule_c") is False
    assert restored.is_enabled(7001, "rule_c") is True


def test_file_save_load_roundtrip(tmp_path: Path):
    s = GroupRuleSwitch()
    s.disable(7001, "rule_a")
    s.disable(7002, "rule_c")
    path = tmp_path / "rule_switch.json"
    s.save(path)

    loaded = GroupRuleSwitch()
    loaded.load(path)
    assert loaded.is_enabled(7001, "rule_a") is False
    assert loaded.is_enabled(7002, "rule_c") is False


def test_load_missing_file_is_noop(tmp_path: Path):
    s = GroupRuleSwitch()
    s.load(tmp_path / "missing.json")
    assert len(s.disabled) == 0
