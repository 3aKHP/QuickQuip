from __future__ import annotations

from pathlib import Path

from quickquip.chat.rule_switch import GroupRuleSwitch


def test_defaults_to_enabled():
    s = GroupRuleSwitch()
    assert s.is_enabled(7001, "divine_arrival") is True


def test_disable_and_enable():
    s = GroupRuleSwitch()
    assert s.disable(7001, "divine_arrival") is True
    assert s.is_enabled(7001, "divine_arrival") is False
    assert s.enable(7001, "divine_arrival") is True
    assert s.is_enabled(7001, "divine_arrival") is True


def test_disable_unknown_rule_returns_false():
    s = GroupRuleSwitch()
    assert s.disable(7001, "not_a_rule") is False


def test_group_isolation():
    s = GroupRuleSwitch()
    s.disable(7001, "play_target")
    assert s.is_enabled(7001, "play_target") is False
    assert s.is_enabled(7002, "play_target") is True


def test_list_disabled():
    s = GroupRuleSwitch()
    s.disable(7001, "play_target")
    s.disable(7001, "like_reply")
    disabled = s.list_disabled(7001)
    assert "play_target" in disabled
    assert "like_reply" in disabled


def test_format_shows_on_off_markers():
    s = GroupRuleSwitch()
    s.disable(7001, "play_target")
    out = s.format_rules(7001)
    assert "[OFF] play_target" in out
    assert "[ON] divine_arrival" in out


def test_lru_eviction():
    s = GroupRuleSwitch(max_groups=2)
    s.disable(1, "divine_arrival")
    s.disable(2, "divine_arrival")
    s.disable(3, "divine_arrival")
    assert list(s.disabled.keys()) == ["2", "3"]


def test_dict_roundtrip():
    s = GroupRuleSwitch()
    s.disable(7001, "divine_arrival")
    s.disable(7001, "play_target")
    s.disable(7002, "like_reply")
    snapshot = s.to_dict()
    restored = GroupRuleSwitch()
    restored.from_dict(snapshot)
    assert restored.is_enabled(7001, "divine_arrival") is False
    assert restored.is_enabled(7001, "play_target") is False
    assert restored.is_enabled(7002, "like_reply") is False
    assert restored.is_enabled(7001, "like_reply") is True


def test_file_save_load_roundtrip(tmp_path: Path):
    s = GroupRuleSwitch()
    s.disable(7001, "divine_arrival")
    s.disable(7002, "like_reply")
    path = tmp_path / "rule_switch.json"
    s.save(path)

    loaded = GroupRuleSwitch()
    loaded.load(path)
    assert loaded.is_enabled(7001, "divine_arrival") is False
    assert loaded.is_enabled(7002, "like_reply") is False


def test_load_missing_file_is_noop(tmp_path: Path):
    s = GroupRuleSwitch()
    s.load(tmp_path / "missing.json")
    assert len(s.disabled) == 0
