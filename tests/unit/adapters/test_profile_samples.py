from __future__ import annotations

from quickquip.adapters.nonebot.commands import _parse_profile_mode, _select_profile_samples


def test_select_profile_samples_keeps_recent_target_messages():
    messages = [
        {"user_id": "2", "text": "别人"},
        {"user_id": "1", "text": "  第一条  "},
        {"user_id": "1", "text": ""},
    ]
    messages.extend({"user_id": "1", "text": f"消息{i}"} for i in range(45))

    samples = _select_profile_samples(messages, "1", limit=40, max_chars=4)

    assert len(samples) == 40
    assert samples[0] == "消息5"
    assert samples[-1] == "消息44"
    assert "别人" not in samples


def test_select_profile_samples_full_keeps_all_without_truncation():
    messages = [
        {"user_id": "1", "text": "第一条很长很长"},
        {"user_id": "1", "text": "第二条很长很长"},
    ]

    samples = _select_profile_samples(messages, "1", limit=None, max_chars=None)

    assert samples == ["第一条很长很长", "第二条很长很长"]


def test_parse_profile_mode_accepts_mode_before_or_after_at():
    assert _parse_profile_mode("/profile short [CQ:at,qq=1]").id == "short"
    assert _parse_profile_mode("/profile [CQ:at,qq=1] long").id == "long"
    assert _parse_profile_mode("/profile [CQ:at,qq=1]").id == "middle"
