from __future__ import annotations

from pathlib import Path

from quickquip.chat.message_stats import GroupStatsTracker


def test_record_and_lookup():
    t = GroupStatsTracker()
    t.record_message(9001, "u1", "张三")
    t.record_message(9001, "u2", "李四")
    t.record_message(9001, "u1", "张三")
    gs = t.get_stats(9001)
    assert gs is not None
    assert gs.total_messages == 3
    assert gs.user_messages == {"u1": 2, "u2": 1}
    assert gs.user_names == {"u1": "张三", "u2": "李四"}


def test_record_triggers():
    t = GroupStatsTracker()
    t.record_message(9001, "u1", "张三")
    t.record_trigger(9001, "divine_arrival")
    t.record_trigger(9001, "divine_arrival")
    t.record_trigger(9001, "play_target")
    gs = t.get_stats(9001)
    assert gs.rule_triggers == {"divine_arrival": 2, "play_target": 1}


def test_format_uses_stored_names():
    t = GroupStatsTracker()
    t.record_message(9001, "u1", "张三")
    t.record_message(9001, "u1", "张三")
    t.record_trigger(9001, "divine_arrival")
    t.record_trigger(9001, "divine_arrival")
    out = t.format_stats(9001)
    assert "消息总数：2" in out
    assert "张三 — 2 条" in out
    assert "divine_arrival — 2 次" in out


def test_format_accepts_name_resolver_override():
    t = GroupStatsTracker()
    t.record_message(9001, "u1", "张三")
    t.record_message(9001, "u1", "张三")
    out = t.format_stats(9001, name_resolver={"u1": "覆盖名"})
    assert "覆盖名 — 2 条" in out


def test_empty_stats_message():
    t = GroupStatsTracker()
    assert t.format_stats(9999) == "暂无统计数据"


def test_reset():
    t = GroupStatsTracker()
    t.record_message(9001, "u1")
    t.reset(9001)
    assert t.get_stats(9001) is None
    assert t.format_stats(9001) == "暂无统计数据"


def test_group_isolation():
    t = GroupStatsTracker()
    t.record_message(8001, "u1")
    t.record_message(8002, "u1")
    assert t.get_stats(8001).total_messages == 1
    assert t.get_stats(8002).total_messages == 1


def test_lru_eviction():
    t = GroupStatsTracker(max_groups=2)
    t.record_message(1, "u1")
    t.record_message(2, "u1")
    t.record_message(3, "u1")
    assert list(t.stats.keys()) == ["2", "3"]


def test_dict_roundtrip():
    t = GroupStatsTracker()
    t.record_message(7001, "u1", "张三")
    t.record_message(7001, "u2", "李四")
    t.record_message(7001, "u1", "张三")
    t.record_trigger(7001, "divine_arrival")
    t.record_trigger(7001, "divine_arrival")
    snapshot = t.to_dict()

    restored = GroupStatsTracker()
    restored.from_dict(snapshot)
    gs = restored.get_stats(7001)
    assert gs.total_messages == 3
    assert gs.user_messages["u1"] == 2
    assert gs.user_names["u1"] == "张三"
    assert gs.rule_triggers["divine_arrival"] == 2


def test_file_save_load_roundtrip(tmp_path: Path):
    t = GroupStatsTracker()
    t.record_message(7001, "u1", "张三")
    t.record_trigger(7001, "divine_arrival")
    stats_file = tmp_path / "stats.json"
    t.save(stats_file)

    loaded = GroupStatsTracker()
    loaded.load(stats_file)
    gs = loaded.get_stats(7001)
    assert gs.total_messages == 1
    assert gs.user_names["u1"] == "张三"


def test_load_missing_file_is_noop(tmp_path: Path):
    t = GroupStatsTracker()
    t.load(tmp_path / "does_not_exist.json")
    assert len(t.stats) == 0
