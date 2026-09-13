#!/usr/bin/env python3
"""Preview or explicitly backfill record references; original content is retained."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT if SOURCE_ROOT.is_dir() else PROJECT_ROOT))

from quickquip.common.identity_sources import identities  # noqa: E402
from quickquip.common.paths import LLM_DB_PATH, QUOTES_DB_PATH, OFFLINE_MESSAGES_DB_PATH  # noqa: E402
from quickquip.common.record_content import legacy, references, render, validate  # noqa: E402
from quickquip.common.record_storage import migrate, save_parts  # noqa: E402

DATABASES = {"memories": LLM_DB_PATH, "quotes": QUOTES_DB_PATH, "offline_messages": OFFLINE_MESSAGES_DB_PATH}


class ApplyResult(Enum):
    WRITTEN = "written"
    INDEX_REPAIRED = "index_repaired"
    CONCURRENT_SKIPPED = "concurrent_skipped"
    UNCHANGED = "unchanged"


def _iter_rows(reader, table, group, record_id, batch_size):
    last_id = 0
    while True:
        conditions, params = ["id > ?"], [last_id]
        if group is not None:
            conditions.append("group_id=?")
            params.append(str(group))
        if record_id is not None:
            conditions.append("id=?")
            params.append(record_id)
        rows = reader.execute(f"SELECT * FROM {table} WHERE {' AND '.join(conditions)} ORDER BY id LIMIT ?", (*params, batch_size)).fetchall()
        if not rows:
            return
        yield from rows
        last_id = rows[-1]["id"]


def _prepare_writer(reader, path, table, report):
    backup = path.with_name(path.name + ".identities-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".bak")
    with closing(sqlite3.connect(backup)) as target:
        reader.backup(target)
    if report:
        report({"backup": str(backup)})
    writer = sqlite3.connect(path)
    try:
        with writer:
            migrate(writer, table)
    except Exception:
        writer.close()
        raise
    return writer


def _preview_row(row, body):
    return {"id": row["id"], "group": row["group_id"], "content": row["content"],
            "content_display": render(body, identities.snapshot(row["group_id"]))}


def _apply_row(writer, table, row, encoded, body):
    with writer:
        writer.execute("BEGIN IMMEDIATE")
        current = writer.execute(f"SELECT content, content_parts_json FROM {table} WHERE id=?", (row["id"],)).fetchone()
        if current is None or current[0] != row["content"] or current[1] != encoded:
            return ApplyResult.CONCURRENT_SKIPPED
        if encoded is None:
            save_parts(writer, table, row["id"], row["group_id"], body)
            return ApplyResult.WRITTEN
        existing = {r[0] for r in writer.execute(f"SELECT qq FROM {table}_member_refs WHERE record_id=?", (row["id"],))}
        missing = references(body) - existing
        writer.executemany(f"INSERT INTO {table}_member_refs(group_id, record_id, qq) VALUES (?, ?, ?)", [(row["group_id"], row["id"], qq) for qq in missing])
        return ApplyResult.INDEX_REPAIRED if missing else ApplyResult.UNCHANGED


def backfill(path, table, *, apply=False, group=None, record_id=None, batch_size=200, before_write=None, preview_limit=0, report=None):
    counts = dict(scanned=0, convertible=0, unparsed=0, existing=0, concurrent_skipped=0, failed=0, written=0, index_repaired=0)
    path = Path(path).resolve()
    if table not in DATABASES:
        raise ValueError("unsupported table")
    if batch_size < 1 or preview_limit < 0:
        raise ValueError("batch_size must be positive and preview_limit nonnegative")
    # Preview neither creates a database nor migrates its schema.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as reader:
        reader.row_factory = sqlite3.Row
        if "content" not in {r[1] for r in reader.execute(f"PRAGMA table_info({table})")}:
            raise ValueError(f"missing record table: {table}")
        writer = _prepare_writer(reader, path, table, report) if apply else None
        try:
            for row in _iter_rows(reader, table, group, record_id, batch_size):
                counts["scanned"] += 1
                try:
                    encoded = row["content_parts_json"] if "content_parts_json" in row.keys() else None
                    body = validate(json.loads(encoded), max_length=1_000_000) if encoded is not None else legacy(row["content"])
                    category = "existing" if encoded is not None else "convertible" if any(p["type"] != "text" for p in body["parts"]) else "unparsed"
                    counts[category] += 1
                    if encoded is None and counts["scanned"] <= preview_limit and report:
                        report(_preview_row(row, body))
                    if writer is not None:
                        if before_write:
                            before_write(row)
                        result = _apply_row(writer, table, row, encoded, body)
                        if result is not ApplyResult.UNCHANGED:
                            counts[result.value] += 1
                except Exception as exc:
                    counts["failed"] += 1
                    if report:
                        report({"id": row["id"], "error": str(exc)})
        finally:
            if writer is not None:
                writer.close()
    return counts


def _emit(event):
    print(json.dumps(event, ensure_ascii=False), file=sys.stderr if "error" in event else sys.stdout)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", choices=[*DATABASES, "all"], default="all")
    parser.add_argument("--path", type=Path, help="Override the selected database path")
    parser.add_argument("--group")
    parser.add_argument("--record-id", type=int)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--preview-limit", type=int, default=10, help="Maximum record examples per database; 0 prints counts only")
    args = parser.parse_args(argv)
    if args.path and args.database == "all":
        parser.error("--path requires a single --database")
    if args.batch_size < 1 or args.preview_limit < 0:
        parser.error("--batch-size must be positive and --preview-limit nonnegative")
    failed = False
    for table, default in DATABASES.items():
        if args.database not in {table, "all"}:
            continue
        try:
            counts = backfill(args.path or default, table, apply=args.apply, group=args.group, record_id=args.record_id, batch_size=args.batch_size, preview_limit=args.preview_limit, report=_emit)
            failed |= bool(counts["failed"])
            _emit({"database": table, **counts})
        except Exception as exc:
            failed = True
            _emit({"database": table, "failed": 1, "error": str(exc)})
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
