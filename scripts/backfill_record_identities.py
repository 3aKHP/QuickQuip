#!/usr/bin/env python3
"""Preview or explicitly backfill record references; original content is retained."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from quickquip.common.paths import LLM_DB_PATH, QUOTES_DB_PATH, OFFLINE_MESSAGES_DB_PATH
from quickquip.common.record_content import legacy, migrate, references, render, save_parts, validate

DATABASES = {"memories": LLM_DB_PATH, "quotes": QUOTES_DB_PATH, "offline_messages": OFFLINE_MESSAGES_DB_PATH}


def backfill(path, table, *, apply=False, group=None, record_id=None, batch_size=200, before_write=None, preview_limit=0):
    counts = dict(scanned=0, convertible=0, unparsed=0, existing=0, concurrent_skipped=0, failed=0, written=0, index_repaired=0)
    path = Path(path).resolve()
    if table not in DATABASES:
        raise ValueError("unsupported table")
    # Preview must neither create a database nor migrate its schema.
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as reader:
        reader.row_factory = sqlite3.Row
        columns = {r[1] for r in reader.execute(f"PRAGMA table_info({table})")}
        if "content" not in columns:
            raise ValueError(f"missing record table: {table}")
        writer = None
        try:
            if apply:
                backup = path.with_name(path.name + ".identities-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".bak")
                with sqlite3.connect(backup) as target:
                    reader.backup(target)
                print(json.dumps({"backup": str(backup)}, ensure_ascii=False))
                writer = sqlite3.connect(path)
                with writer:
                    migrate(writer, table)
            last_id = 0
            while True:
                conditions = ["id > ?"]
                params = [last_id]
                if group is not None:
                    conditions.append("group_id=?")
                    params.append(str(group))
                if record_id is not None:
                    conditions.append("id=?")
                    params.append(record_id)
                rows = reader.execute(f"SELECT * FROM {table} WHERE {' AND '.join(conditions)} ORDER BY id LIMIT ?", (*params, batch_size)).fetchall()
                if not rows:
                    break
                for row in rows:
                    last_id = row["id"]
                    counts["scanned"] += 1
                    encoded = row["content_parts_json"] if "content_parts_json" in row.keys() else None
                    try:
                        body = validate(json.loads(encoded), max_length=1_000_000) if encoded is not None else legacy(row["content"])
                    except (ValueError, TypeError) as exc:
                        counts["failed"] += 1
                        print(json.dumps({"id": last_id, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
                        continue
                    if encoded is not None:
                        counts["existing"] += 1
                    else:
                        special = any(p["type"] != "text" for p in body["parts"])
                        counts["convertible" if special else "unparsed"] += 1
                        if counts["scanned"] <= preview_limit:
                            from quickquip.app.identities import identities
                            print(json.dumps({"id": last_id, "group": row["group_id"], "content": row["content"], "content_display": render(body, identities.snapshot(row["group_id"]))}, ensure_ascii=False))
                    if not apply:
                        continue
                    try:
                        if before_write:
                            before_write(row)
                        wrote = repaired = False
                        with writer:
                            # Reserve the writer before checking the content and missing-parts predicate.
                            writer.execute("BEGIN IMMEDIATE")
                            current = writer.execute(f"SELECT content, content_parts_json FROM {table} WHERE id=?", (last_id,)).fetchone()
                            if current is None or current[0] != row["content"] or current[1] != encoded:
                                counts["concurrent_skipped"] += 1
                                continue
                            if encoded is None:
                                save_parts(writer, table, last_id, row["group_id"], body)
                                wrote = True
                            else:
                                existing_refs = {r[0] for r in writer.execute(f"SELECT qq FROM {table}_member_refs WHERE record_id=?", (last_id,))}
                                missing = references(body) - existing_refs
                                writer.executemany(f"INSERT INTO {table}_member_refs(group_id, record_id, qq) VALUES (?, ?, ?)", [(row["group_id"], last_id, qq) for qq in missing])
                                repaired = bool(missing)
                        counts["written"] += wrote
                        counts["index_repaired"] += repaired
                    except Exception as exc:
                        counts["failed"] += 1
                        print(json.dumps({"id": last_id, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        finally:
            if writer:
                writer.close()
    return counts


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
            counts = backfill(args.path or default, table, apply=args.apply, group=args.group, record_id=args.record_id, batch_size=args.batch_size, preview_limit=args.preview_limit)
            failed |= bool(counts["failed"])
            print(json.dumps({"database": table, **counts}, ensure_ascii=False))
        except Exception as exc:
            failed = True
            print(json.dumps({"database": table, "failed": 1, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
