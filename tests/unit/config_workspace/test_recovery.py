"""Abrupt process termination and commit receipts across real files and SQLite."""

import subprocess
import sys

import pytest

from quickquip.common.config_writes import ConfigurationBusy, configuration_write
from quickquip.configuration.activity import service_guard
from quickquip.configuration.errors import ConfigError
from quickquip.configuration import snapshot as content
from quickquip.config_workspace import transactions
from quickquip.config_workspace.service import Workspace

from .test_qqconf import edit, files, provider


def crash(root, patch, action="pack"):
    script = f"""
import os
from pathlib import Path
from quickquip.config_workspace.service import Workspace
from quickquip.config_workspace.storage import Storage
from quickquip.config_workspace import transactions, storage
{patch}
Workspace(root=Path({str(root)!r})).{action}()
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=30)
    assert result.returncode == 71, result.stderr.decode()


def test_ordinary_source_failure_restores_database_files_and_workspace(
    workspace, project, monkeypatch
):
    root, _ = project
    edit(provider(workspace), lambda value: value["parameters"].update(temperature=0.2))
    (workspace.storage.directory / ".env").write_text("PORT=5800\n")
    before, working = content.read(root), files(workspace.storage.directory)
    install = transactions.install_database
    calls = []

    def fail_once(*args):
        install(*args)
        calls.append(True)
        if len(calls) == 1:
            raise OSError("synthetic disk failure")

    monkeypatch.setattr(transactions, "install_database", fail_once)
    with pytest.raises(OSError, match="disk failure"):
        workspace.pack()
    assert content.read(root) == before
    assert files(workspace.storage.directory) == working
    assert not workspace._pending()


def test_source_crash_blocks_consumers_and_next_pack_recovers(workspace, project):
    root, service = project
    runtime = (root / "data/config_runtime.db").read_bytes()
    revision = service.read()["revision"]
    edit(provider(workspace), lambda value: value["parameters"].update(temperature=0.2))
    crash(
        root,
        """
original = transactions.install_database
def interrupt(*args):
    original(*args)
    os._exit(71)
transactions.install_database = interrupt
""",
    )
    before = files(root)
    assert workspace.refresh()["recovery_required"]
    assert files(root) == before
    with pytest.raises(ConfigError, match="recover"):
        with service_guard(root, "bot"):
            pass
    with pytest.raises(ConfigurationBusy):
        with configuration_write(root / "data"):
            pass
    workspace.pack()
    assert not workspace._pending()
    assert service.read()["revision"] == revision + 1
    assert service.read()["document"]["providers"][0]["parameters"]["temperature"] == 0.2
    assert (root / "data/config_runtime.db").read_bytes() == runtime


def test_recovery_preserves_unrelated_external_database_edit(workspace, project):
    root, service = project
    edit(provider(workspace), lambda value: value["parameters"].update(temperature=0.2))
    crash(
        root,
        """
original = transactions.install_database
def interrupt(*args):
    original(*args)
    os._exit(71)
transactions.install_database = interrupt
""",
    )
    import sqlite3

    with sqlite3.connect(root / "config/managed/config.db") as connection:
        connection.execute("INSERT INTO niuniu_group_text VALUES('98765','safe')")
    before = content.read(root)
    with pytest.raises(ConfigError, match="External database edit"):
        workspace.pack()
    assert content.read(root) == before
    assert workspace._pending()


@pytest.mark.parametrize("receipt", [False, True])
def test_candidate_crash_recovers_and_committed_receipt_keeps_later_edits(
    workspace, project, receipt
):
    root, _ = project
    (root / "data/qqconf/services/web.json").unlink()
    edit(provider(workspace), lambda value: value["parameters"].update(temperature=0.2))
    workspace.pack()
    edit(provider(workspace), lambda value: value["parameters"].update(temperature=0.3))
    patch = (
        """
original = Storage.save
def interrupt(self, *args):
"""
        + ("    original(self, *args)\n" if receipt else "")
        + """    os._exit(71)
Storage.save = interrupt
"""
    )
    crash(root, patch)
    before = files(root)
    assert workspace.refresh()["recovery_required"]
    assert files(root) == before
    edit(provider(workspace), lambda value: value["parameters"].update(timeout_seconds=55.0))
    workspace.pack()
    assert not workspace._pending()
    target = content.read(root / ".config-staging")
    assert target["document"]["providers"][0]["parameters"]["temperature"] == 0.3
    assert target["document"]["providers"][0]["parameters"]["timeout_seconds"] == 55.0
    assert not (root / ".config-staging.previous").exists()


def test_interrupted_initial_unpack_can_be_retried(project):
    root, _ = project
    crash(
        root,
        """
original = storage.install
def interrupt(*args):
    original(*args)
    os._exit(71)
storage.install = interrupt
""",
        action="unpack",
    )
    workspace = Workspace(root=root)
    before = files(root)
    assert workspace.refresh()["recovery_required"]
    assert files(root) == before
    workspace.unpack()
    assert not workspace._pending()
    assert workspace.pack()["phase"] == "unchanged"


def test_source_commit_receipt_preserves_later_source_and_workspace_edits(workspace, project):
    root, service = project
    edit(provider(workspace), lambda value: value["parameters"].update(temperature=0.2))
    crash(
        root,
        """
original = Storage.save
def interrupt(self, *args):
    original(self, *args)
    os._exit(71)
Storage.save = interrupt
""",
    )
    # Raw sqlite edits simulate a separate offline operator after the committed write.
    import json
    import sqlite3

    with sqlite3.connect(root / "config/managed/config.db") as connection:
        doc = json.loads(connection.execute("SELECT document FROM config_meta").fetchone()[0])
        doc["providers"][0]["parameters"]["timeout_seconds"] = 49.0
        connection.execute("UPDATE config_meta SET document=?", (json.dumps(doc),))
        from quickquip.llm.config_store import project_document

        project_document(connection, doc)
    edit(provider(workspace), lambda value: value["parameters"].update(temperature=0.4))
    workspace.pack()
    result = service.read()["document"]["providers"][0]["parameters"]
    assert result["temperature"] == 0.4
    assert result["timeout_seconds"] == 49.0
