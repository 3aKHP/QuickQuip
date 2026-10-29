"""Read both LLM branches and all managed configuration without source writes."""

import json
import sqlite3

from quickquip.configuration import images, snapshot
from quickquip.configuration.errors import ConfigError
from quickquip.llm.config_document import upgrade_document


def read(layout, source="draft"):
    if source not in ("draft", "published"):
        raise ConfigError("invalid_field", "Expected draft or published", "source")
    files = layout.read_files()
    result = snapshot.read(layout.root, files=files)
    with images.read_only(layout.database) as connection:
        revision = connection.execute("SELECT draft_revision FROM config_meta").fetchone()[0]
    with images.read_only(layout.root / "data/config_runtime.db") as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        published = connection.execute(
            "SELECT revision,document FROM execution_snapshots JOIN publication "
            "ON revision=published_revision"
        ).fetchone()
        pending = connection.execute(
            "SELECT COUNT(*) FROM config_operations WHERE kind='apply' "
            "AND status IN ('queued','running')"
        ).fetchone()[0]
    if published is None:
        raise ConfigError("database_corrupt", "Published configuration is missing")
    draft = result["document"]
    document = upgrade_document(json.loads(published["document"]))[0]
    if source == "published":
        result["document"] = document
    # Detect file editors and completed DB edits racing the paired read.
    latest = snapshot.read(layout.root, files=layout.read_files())
    if latest != {**result, "document": draft}:
        raise ConfigError("configuration_busy", "Configuration changed while reading; retry")
    return {
        "snapshot": result,
        "draft": draft,
        "published": document,
        "draft_revision": revision,
        "published_revision": published["revision"],
        "pending": pending,
    }
