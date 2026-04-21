from __future__ import annotations

from quickquip.chat.repeat_detector import GroupRepeatDetector


def test_follow_read_on_different_users():
    d = GroupRepeatDetector()
    assert d.process(group_id=1001, user_id=1, text="复读") is None
    result = d.process(group_id=1001, user_id=2, text="复读")
    assert result is not None
    assert result["rule_name"] == "repeat_follow_read"
    assert result["rate_limit_key"] == "repeat_follow_read"
    assert result["reply"] == "复读"


def test_trim_last_on_same_user_dup():
    d = GroupRepeatDetector()
    assert d.process(group_id=1001, user_id=1, text="晚安") is None
    result = d.process(group_id=1001, user_id=1, text="晚安")
    assert result is not None
    assert result["rule_name"] == "repeat_trim_last"
    assert result["rate_limit_key"] == "repeat_trim_last"
    assert result["reply"] == "晚"


def test_same_user_warning_after_four_repeats():
    d = GroupRepeatDetector()
    assert d.process(group_id=1001, user_id=1, text="哈哈") is None
    trim = d.process(group_id=1001, user_id=1, text="哈哈")
    assert trim is not None
    assert trim["rule_name"] == "repeat_trim_last"
    assert trim["reply"] == "哈"
    assert d.process(group_id=1001, user_id=1, text="哈哈") is None
    warning = d.process(group_id=1001, user_id=1, text="哈哈")
    assert warning is not None
    assert warning["rule_name"] == "repeat_same_user_warning"
    assert warning["rate_limit_key"] == "repeat_same_user_warning"
    assert warning["at_user_id"] == "1"
    assert warning["reply"] == "艾斯比"


def test_same_user_four_consecutive_triggers_warning_not_trim():
    d = GroupRepeatDetector()
    assert d.process(group_id=1001, user_id=9, text="测试测试") is None
    assert d.process(group_id=1001, user_id=9, text="测试测试")["rule_name"] == "repeat_trim_last"
    assert d.process(group_id=1001, user_id=9, text="测试测试") is None
    assert (
        d.process(group_id=1001, user_id=9, text="测试测试")["rule_name"]
        == "repeat_same_user_warning"
    )


def test_group_isolation():
    d = GroupRepeatDetector()
    assert d.process(group_id=2001, user_id=1, text="群消息") is None
    assert d.process(group_id=2002, user_id=2, text="群消息") is None
    follow = d.process(group_id=2001, user_id=3, text="群消息")
    assert follow is not None
    assert follow["rule_name"] == "repeat_follow_read"


def test_lru_eviction():
    d = GroupRepeatDetector(max_groups=2)
    d.process(group_id=1, user_id=1, text="A")
    d.process(group_id=2, user_id=1, text="B")
    d.process(group_id=3, user_id=1, text="C")
    assert list(d.states.keys()) == ["2", "3"]
