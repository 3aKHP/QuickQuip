"""历史聊天回灌脚本的结果统计与退出状态。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from quickquip.chat.archive import RecordResult


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "backfill_chat_archive.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("backfill_chat_archive", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backfill_reports_write_failure_and_exits_nonzero(tmp_path, monkeypatch, capsys):
    module = _load_script()
    source = tmp_path / "daily_msgs" / "10001"
    source.mkdir(parents=True)
    (source / "2026-09-10.jsonl").write_text(
        '{"sender":"n","text":"内容","ts":1,"user_id":"1"}\n', encoding="utf-8"
    )

    class FailingArchive:
        def stats(self):
            return {"available": True, "messages": 0, "groups": 0}

        def record_result(self, *args, **kwargs):
            return RecordResult.FAILED

    monkeypatch.setattr(module, "ChatArchive", FailingArchive)
    monkeypatch.setattr(module, "DAILY_MESSAGES_DIR", source.parent)
    monkeypatch.setattr(module, "WORDCLOUD_MESSAGES_DIR", tmp_path / "missing")
    monkeypatch.setattr(sys, "argv", [str(SCRIPT_PATH)])

    assert module.main() == 1
    output = capsys.readouterr().out
    assert "写入失败 1 条" in output
    assert "新写入 0 条" in output


def test_backfill_dry_run_only_counts_input(tmp_path, monkeypatch, capsys):
    module = _load_script()
    source = tmp_path / "daily_msgs" / "10001"
    source.mkdir(parents=True)
    (source / "2026-09-10.jsonl").write_text(
        '{"sender":"n","text":"内容","ts":1,"user_id":"1"}\n', encoding="utf-8"
    )

    class DryRunArchive:
        def stats(self):
            return {"available": True, "messages": 0, "groups": 0}

        def record_result(self, *args, **kwargs):
            raise AssertionError("dry-run must not write")

    monkeypatch.setattr(module, "ChatArchive", DryRunArchive)
    monkeypatch.setattr(module, "DAILY_MESSAGES_DIR", source.parent)
    monkeypatch.setattr(module, "WORDCLOUD_MESSAGES_DIR", tmp_path / "missing")
    monkeypatch.setattr(sys, "argv", [str(SCRIPT_PATH), "--dry-run"])

    assert module.main() == 0
    output = capsys.readouterr().out
    assert "daily_msgs: 读取 1 条" in output
    assert "归档现状：0 条 / 0 群（dry-run 未写入）" in output


def test_backfill_real_archive_retries_failed_rows_and_remains_idempotent(tmp_path, monkeypatch, capsys):
    import sqlite3
    from unittest.mock import patch
    from quickquip.chat.archive import ChatArchive

    module = _load_script()
    source = tmp_path / "daily_msgs" / "10001"
    source.mkdir(parents=True)
    (source / "2026-09-10.jsonl").write_text(
        '{"sender":"n","text":"内容","ts":1,"user_id":"1"}\n', encoding="utf-8"
    )
    archive = ChatArchive(tmp_path / "archive.db")
    monkeypatch.setattr(module, "ChatArchive", lambda: archive)
    monkeypatch.setattr(module, "DAILY_MESSAGES_DIR", source.parent)
    monkeypatch.setattr(module, "WORDCLOUD_MESSAGES_DIR", tmp_path / "missing")
    monkeypatch.setattr(sys, "argv", [str(SCRIPT_PATH)])
    original = archive.record_result
    def fail_write(*args, **kwargs):
        with patch.object(archive, "_connect", side_effect=sqlite3.OperationalError("database is locked")):
            return original(*args, **kwargs)
    with patch.object(archive, "record_result", fail_write):
        assert module.main() == 1
    assert archive.stats()["messages"] == 0
    assert "写入失败 1 条" in capsys.readouterr().out
    assert module.main() == 0
    assert "新写入 1 条" in capsys.readouterr().out
    assert module.main() == 0
    assert "已存在 1 条" in capsys.readouterr().out
    assert archive.stats()["messages"] == 1
