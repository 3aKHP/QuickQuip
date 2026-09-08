"""ChatArchive：忠实归档、去重与窗口读取（1.15.2 A 线）。"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from quickquip.chat.archive import ChatArchive


def _ts(minutes: float) -> float:
    return datetime(2026, 9, 9, 6, 0, tzinfo=timezone.utc).timestamp() + minutes * 60


def test_record_and_read_window_round_trip(tmp_path: Path):
    archive = ChatArchive(tmp_path / "a.db")
    archive.record("10001", "张三", "第一条", ts=_ts(0), user_id="1", message_id="m1")
    archive.record("10001", "李四", "第二条", ts=_ts(1), user_id="2", message_id="m2", image_urls=["https://img/1.png"])
    archive.record("10002", "王五", "别群", ts=_ts(2), user_id="3", message_id="m3")

    window = archive.read_window("10001", _ts(-1), _ts(10))
    assert [m["text"] for m in window] == ["第一条", "第二条"]
    assert window[0]["user_id"] == "1"
    assert window[1]["image_count"] == 1
    # 窗口边界 [start, end)
    assert archive.read_window("10001", _ts(0.5), _ts(10))[-1]["text"] == "第二条"
    assert archive.read_window("10001", _ts(1), _ts(10))[0]["text"] == "第二条"


def test_dedupe_by_message_id(tmp_path: Path):
    archive = ChatArchive(tmp_path / "a.db")
    assert archive.record("10001", "n", "内容", ts=_ts(0), message_id="m1") is True
    assert archive.record("10001", "n", "内容", ts=_ts(0), message_id="m1") is False
    assert len(archive.read_all("10001")) == 1


def test_dedupe_by_content_hash_without_message_id(tmp_path: Path):
    # 回灌等无 message_id 来源：同 group|ts|sender|text 视为同一条。
    archive = ChatArchive(tmp_path / "a.db")
    assert archive.record("10001", "n", "重复内容", ts=_ts(0)) is True
    assert archive.record("10001", "n", "重复内容", ts=_ts(0)) is False
    # ts 不同则不是同一条
    assert archive.record("10001", "n", "重复内容", ts=_ts(1)) is True
    assert len(archive.read_all("10001")) == 2


def test_blank_text_skipped_and_bad_group_rejected(tmp_path: Path):
    archive = ChatArchive(tmp_path / "a.db")
    archive.record("10001", "n", "   ")
    assert archive.read_all("10001") == []
    with pytest.raises(ValueError):
        archive.record("not-a-number", "n", "hello")


def test_image_urls_and_stats(tmp_path: Path):
    archive = ChatArchive(tmp_path / "a.db")
    archive.record("10001", "n", "带图", ts=_ts(0), message_id="m1", image_urls=["u1", "u2"])
    stats = archive.stats()
    assert stats["available"] is True
    assert stats["messages"] == 1
    assert stats["groups"] == 1


def test_dedupe_same_ts_same_text_without_message_id(tmp_path: Path):
    """Bot Review 建议：ts 与 text 完全相同的无 ID 写入仍应去重（回灌双源）。"""
    archive = ChatArchive(tmp_path / "a.db")
    assert archive.record("10001", "n", "刷屏", ts=_ts(0)) is True
    assert archive.record("10001", "n", "刷屏", ts=_ts(0)) is False
    # 同秒同文但出现序号不同（occurrence）是不同消息，保留
    assert archive.record("10001", "n", "刷屏", ts=_ts(0), occurrence=1) is True
    assert len(archive.read_all("10001")) == 2


def test_read_window_excludes_bot_rows(tmp_path: Path):
    """exclude_user_ids 供统计口径消费侧剔除 bot 行；不传则保全量。"""
    archive = ChatArchive(tmp_path / "a.db")
    base = 1_700_000_000.0
    archive.record("10001", "张三", "用户消息", ts=base, user_id="1001")
    archive.record("10001", "QuickQuip", "bot 消息", ts=base + 1, user_id="9999")
    archive.record("10001", "路人", "无归因消息", ts=base + 2)

    full = archive.read_window("10001", base, base + 10)
    assert [m["text"] for m in full] == ["用户消息", "bot 消息", "无归因消息"]

    filtered = archive.read_window(
        "10001", base, base + 10, exclude_user_ids={"9999"}
    )
    assert [m["text"] for m in filtered] == ["用户消息", "无归因消息"]

    # user_id 为空/None 的行（回灌历史形态）不受过滤影响
    assert archive.read_all("10001", exclude_user_ids={"9999"}) == filtered

    # 空集合不改变行为
    assert archive.read_window("10001", base, base + 10, exclude_user_ids=set()) == full
