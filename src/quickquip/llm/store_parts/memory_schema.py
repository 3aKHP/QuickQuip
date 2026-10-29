"""记忆条目增量迁移；保留旧正文、ID 和成员关联。"""

from quickquip.llm.memory_content import derive_metadata


def migrate_memory_entries(conn) -> None:
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
    definitions = {
        "title": "TEXT NOT NULL DEFAULT ''",
        "description": "TEXT NOT NULL DEFAULT ''",
        "version": "INTEGER NOT NULL DEFAULT 1",
        "source_role": "TEXT NOT NULL DEFAULT 'unknown'",
        "source_user_id": "TEXT",
        "source_message_id": "TEXT",
        "writer": "TEXT NOT NULL DEFAULT 'legacy'",
    }
    for name, definition in definitions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE memories ADD COLUMN {name} {definition}")
    for row in conn.execute("SELECT id, content FROM memories WHERE title=''").fetchall():
        title, description = derive_metadata(row["content"])
        conn.execute(
            "UPDATE memories SET title=?, description=? WHERE id=?", (title, description, row["id"])
        )
    conn.execute("UPDATE memories SET scope='group' WHERE scope='user'")
