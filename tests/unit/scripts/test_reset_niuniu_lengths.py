"""Offline reset candidates retain the source backup and all unrelated data."""

from pathlib import Path
import os
import runpy
import sqlite3
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/maintenance/reset_niuniu_lengths.py"
build_candidate = runpy.run_path(str(SCRIPT))["build_candidate"]


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "backup.db"
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE niuniu_users (
            uid TEXT PRIMARY KEY, length REAL, luck REAL, luck_date TEXT,
            fence_luck REAL, fence_luck_date TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE niuniu_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT, action TEXT,
            origin_length REAL, new_length REAL, created_at TEXT);
        CREATE TABLE retained_extension (value TEXT);
        INSERT INTO retained_extension VALUES ('preserve me');
        INSERT INTO niuniu_users VALUES
            ('11111',1e30,0.000000000123,'2026-10-27',123.456789,'2026-10-27','created-a','updated-a'),
            ('22222',-1e6,7.654321,'2026-10-26',0.000000321,'2026-10-26','created-b','updated-b');
        INSERT INTO niuniu_records VALUES (17,'11111','gluing',9,1e30,'historical');
    """)
    connection.close()
    return path


def test_cli_preview_does_not_write_source_or_output(source):
    before = source.read_bytes()
    output = source.with_name("candidate.db")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--source", str(source), "--output", str(output)],
        check=True, capture_output=True, text=True,
    )
    assert '"applied": false' in result.stdout
    assert source.read_bytes() == before
    assert not output.exists()


def test_candidate_resets_only_lengths_and_retains_records(source):
    before = source.read_bytes()
    output = source.with_name("candidate.db")
    summary = build_candidate(source, output, apply=True)
    assert summary["players"] == summary["added_records"] == 2
    assert source.read_bytes() == before
    original = sqlite3.connect(source)
    candidate = sqlite3.connect(output)
    try:
        old_users = original.execute("SELECT * FROM niuniu_users ORDER BY uid").fetchall()
        new_users = candidate.execute("SELECT * FROM niuniu_users ORDER BY uid").fetchall()
        for old, new in zip(old_users, new_users):
            assert new[1] == 10
            assert new[0] == old[0]
            assert new[2:7] == old[2:7]  # Exact luck precision, dates and registration times.
            assert new[7] != old[7]
        records = candidate.execute("SELECT * FROM niuniu_records ORDER BY id").fetchall()
        assert records[:1] == original.execute("SELECT * FROM niuniu_records").fetchall()
        assert [(r[1], r[2], r[3], r[4]) for r in records[1:]] == [
            ("11111", "reset_length", 1e30, 10), ("22222", "reset_length", -1e6, 10),
        ]
        assert candidate.execute("SELECT * FROM retained_extension").fetchall() == [
            ("preserve me",)
        ]
        assert candidate.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert candidate.execute("PRAGMA journal_mode").fetchone() == ("delete",)
    finally:
        original.close()
        candidate.close()


def test_source_cannot_be_output(source):
    before = source.read_bytes()
    with pytest.raises(ValueError, match="different"):
        build_candidate(source, source, apply=True)
    assert source.read_bytes() == before


def test_repeat_cannot_overwrite_a_candidate(source):
    output = source.with_name("candidate.db")
    build_candidate(source, output, apply=True)
    before = output.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        build_candidate(source, output, apply=True)
    assert output.read_bytes() == before


def test_transaction_failure_removes_candidate_and_preserves_source(source):
    connection = sqlite3.connect(source)
    connection.execute("CREATE TRIGGER fail_reset BEFORE INSERT ON niuniu_records "
                       "WHEN NEW.action='reset_length' BEGIN SELECT RAISE(ABORT,'injected'); END")
    connection.close()
    before = source.read_bytes()
    output = source.with_name("candidate.db")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        build_candidate(source, output, apply=True)
    assert source.read_bytes() == before
    assert not output.exists()
    assert not Path(str(output) + "-journal").exists()


def test_running_wal_source_is_rejected(source):
    connection = sqlite3.connect(source)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("UPDATE niuniu_users SET length=42")
        connection.commit()
        with pytest.raises(ValueError, match="WAL"):
            build_candidate(source, source.with_name("candidate.db"), apply=True)
    finally:
        connection.close()


def test_candidate_flush_uses_a_writable_handle_on_windows(source, monkeypatch):
    """Windows FlushFileBuffers needs write access, unlike POSIX fsync."""
    real_fsync = os.fsync
    flushed = []

    def windows_fsync(descriptor):
        os.write(descriptor, b"")  # Fails for the former read-only handle, without changing data.
        real_fsync(descriptor)
        flushed.append(descriptor)

    monkeypatch.setattr(os, "fsync", windows_fsync)
    output = source.with_name("candidate.db")
    assert build_candidate(source, output, apply=True)["applied"]
    assert output.exists()
    assert flushed


def test_missing_source_is_not_created(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(ValueError, match="does not exist"):
        build_candidate(missing, tmp_path / "candidate.db", apply=True)
    assert not missing.exists()
