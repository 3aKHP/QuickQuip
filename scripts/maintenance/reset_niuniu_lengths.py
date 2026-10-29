"""Build an offline niuniu reset candidate while preserving the source backup.

Run from the project root with --source BACKUP --output CANDIDATE. The default
is a read-only preview; --apply creates a new database with every length at 10 cm.
Stop database consumers and checkpoint WAL before taking the source backup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_candidate(source: Path, output: Path, *, apply: bool = False) -> dict:
    source, output = source.resolve(), output.resolve()
    if source == output:
        raise ValueError("Source and output must be different files")
    if not source.is_file():
        raise ValueError("Source database does not exist")
    if output.exists():
        raise ValueError("Output already exists; choose a new candidate filename")
    wal = Path(str(source) + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise ValueError("Source has a WAL; stop consumers and checkpoint before copying it")
    before_hash = _digest(source)
    original = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    try:
        if original.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("Source database integrity check failed")
        users = original.execute("SELECT * FROM niuniu_users ORDER BY uid").fetchall()
        columns = [r[1] for r in original.execute("PRAGMA table_info(niuniu_users)")]
        uid_index, length_index = columns.index("uid"), columns.index("length")
        updated_index = columns.index("updated_at")
        record_count = original.execute("SELECT COUNT(*) FROM niuniu_records").fetchone()[0]
        summary = {
            "applied": False, "players": len(users), "target_length": 10.0,
            "existing_records": record_count, "source_sha256": before_hash,
        }
        if not apply:
            return summary

        # Exclusive creation prevents accidental overwrites, including a concurrent invocation.
        fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        candidate = None
        try:
            candidate = sqlite3.connect(output)
            original.backup(candidate)
            candidate.execute("PRAGMA journal_mode=DELETE")
            now = datetime.now(timezone.utc).isoformat()
            with candidate:
                candidate.execute(
                    "UPDATE niuniu_users SET length=10.0, updated_at=?", (now,)
                )
                candidate.executemany(
                    "INSERT INTO niuniu_records "
                    "(uid, action, origin_length, new_length, created_at) "
                    "VALUES (?, 'reset_length', ?, 10.0, ?)",
                    [(row[uid_index], row[length_index], now) for row in users],
                )
            actual = candidate.execute("SELECT * FROM niuniu_users ORDER BY uid").fetchall()
            retained = [i for i in range(len(columns)) if i not in (length_index, updated_index)]
            if len(actual) != len(users) or any(
                new[length_index] != 10.0
                or any(old[i] != new[i] for i in retained)
                for old, new in zip(users, actual)
            ):
                raise ValueError("Candidate changed player fields outside length and updated_at")
            if candidate.execute("SELECT COUNT(*) FROM niuniu_records").fetchone()[0] != (
                record_count + len(users)
            ):
                raise ValueError("Candidate record count does not match the reset")
            # Compare the full old record prefix, including IDs and timestamps.
            if candidate.execute(
                "SELECT * FROM niuniu_records ORDER BY id LIMIT ?", (record_count,)
            ).fetchall() != original.execute("SELECT * FROM niuniu_records ORDER BY id").fetchall():
                raise ValueError("Candidate changed existing records")
            if candidate.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ValueError("Candidate integrity check failed")
            candidate.close()
            candidate = None
            with output.open("r+b") as stream:
                os.fsync(stream.fileno())
            if _digest(source) != before_hash:
                raise ValueError("Source changed during candidate preparation")
            summary.update(applied=True, added_records=len(users), candidate_sha256=_digest(output))
            return summary
        except BaseException:
            if candidate is not None:
                candidate.close()
            output.unlink(missing_ok=True)
            Path(str(output) + "-journal").unlink(missing_ok=True)
            raise
    finally:
        original.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = build_candidate(args.source, args.output, apply=args.apply)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"Reset candidate failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
