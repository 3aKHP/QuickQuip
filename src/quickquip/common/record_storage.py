"""SQLite schema and atomic reference writes shared by persistent record stores."""
import json
import sqlite3

from quickquip.common.record_content import references


def checked_table(table):
    if table not in {"memories", "quotes", "offline_messages"}:
        raise ValueError("unsupported record table")
    return table


def migrate(conn, table):
    checked_table(table)
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN content_parts_json TEXT")
    except sqlite3.OperationalError:
        if "content_parts_json" not in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}:
            raise
    conn.execute(f"CREATE TABLE IF NOT EXISTS {table}_member_refs (group_id TEXT NOT NULL, record_id INTEGER NOT NULL, qq TEXT NOT NULL, PRIMARY KEY(record_id, qq))")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_member_refs ON {table}_member_refs(group_id, qq, record_id)")
    conn.execute(f"CREATE TRIGGER IF NOT EXISTS delete_{table}_refs AFTER DELETE ON {table} BEGIN DELETE FROM {table}_member_refs WHERE record_id=OLD.id; END")


def save_parts(conn, table, record_id, scope, body):
    checked_table(table)
    conn.execute(f"UPDATE {table} SET content_parts_json=? WHERE id=?", (json.dumps(body, ensure_ascii=False), record_id))
    conn.execute(f"DELETE FROM {table}_member_refs WHERE record_id=?", (record_id,))
    conn.executemany(f"INSERT INTO {table}_member_refs(group_id, record_id, qq) VALUES (?, ?, ?)", [(str(scope), record_id, qq) for qq in references(body)])
