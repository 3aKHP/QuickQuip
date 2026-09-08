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
