"""Configuration round trips, reconciliation and side effects through the real local API."""

import json
import sqlite3
import subprocess
import sys

import pytest

from quickquip.configuration.activity import offline, service_guard
from quickquip.configuration.errors import ConfigError
from quickquip.config_workspace.codec import decode, encode, parse, render_table
from quickquip.config_workspace.layout import read_tree
from quickquip.config_workspace import content


def provider(workspace):
    return next((workspace.storage.directory / "db/llm/providers").glob("*.toml"))


def edit(path, change):
    raw = path.read_bytes()
    value = decode(parse(raw, path.name))
    change(value)
    path.write_bytes(render_table(encode(value), raw))


def files(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_roundtrip_keeps_values_text_and_runtime_and_is_idempotent(workspace, project):
    root, service = project
    before = content.read(root)
    runtime = (root / "data/config_runtime.db").read_bytes()
    assert content.validate(read_tree(workspace.storage.directory).snapshot) == before
    assert b"[value]" not in provider(workspace).read_bytes()
    revision = service.read()["revision"]
    unpacked = files(workspace.storage.directory)
    first = workspace.pack()
    assert first["phase"] == "unchanged"
    second = workspace.pack()
    assert second == first
    assert service.read()["revision"] == revision
    assert content.read(root) == before
    assert (root / "data/config_runtime.db").read_bytes() == runtime
    assert files(workspace.storage.directory) == unpacked


def test_field_merge_retains_independent_changes_and_refresh_is_readonly(workspace, project):
    root, service = project
    path = provider(workspace)
    path.write_bytes(b"# local explanation\n" + path.read_bytes())
    edit(path, lambda value: value["parameters"].update(temperature=0.7))
    draft = service.read()
    draft["document"]["providers"][0]["parameters"]["timeout_seconds"] = 45.0
    service.replace(draft["document"], draft["revision"])
    before = files(root)
    result = workspace.refresh()
    assert not result["conflicts"]
    assert files(root) == before
    assert any("temperature" in row.get("field", "") for row in result["workspace_changes"])
    assert any("timeout_seconds" in row.get("field", "") for row in result["source_changes"])
    assert workspace.pack()["destination"] == "source"
    parameters = service.read()["document"]["providers"][0]["parameters"]
    assert parameters["temperature"] == 0.7
    assert parameters["timeout_seconds"] == 45.0
    assert provider(workspace).read_bytes().startswith(b"# local explanation\n")
    assert workspace.refresh()["write_changes"] == []


def test_conflicts_do_not_write_and_preference_only_selects_conflicting_fields(workspace, project):
    root, service = project
    edit(provider(workspace), lambda value: value["parameters"].update(temperature=0.3))
    draft = service.read()
    draft["document"]["providers"][0]["parameters"].update(temperature=0.9, timeout_seconds=47.0)
    service.replace(draft["document"], draft["revision"])
    before = files(root)
    assert workspace.refresh()["conflicts"]
    with pytest.raises(ConfigError, match="conflicting"):
        workspace.pack()
    assert files(root) == before
    workspace.pack(prefer="workspace")
    values = service.read()["document"]["providers"][0]["parameters"]
    assert values["temperature"] == 0.3
    assert values["timeout_seconds"] == 47.0


@pytest.mark.parametrize("role", ["bot", "web"])
def test_running_service_creates_complete_candidate_without_changing_source(
    workspace, project, role
):
    root, service = project
    original = content.read(root)
    edit(provider(workspace), lambda value: value["parameters"].update(temperature=0.4))
    with service_guard(root, role):
        result = workspace.pack()
    assert result["destination"] == "candidate"
    assert content.read(root) == original
    candidate = content.read(root / ".config-staging")
    assert candidate["document"]["providers"][0]["parameters"]["temperature"] == 0.4
    assert not (root / ".config-staging/data/config_runtime.db").exists()
    assert (root / ".config-staging/.env").read_bytes() == (root / ".env").read_bytes()
    state = workspace.storage.state()
    assert state["base"] == original
    preview = workspace.refresh()
    assert preview["candidate_pending"]
    assert preview["candidate_matches_workspace"]
    assert service.read("published")["revision"] == 1
    with service_guard(root, role):
        before = files(root / ".config-staging")
        assert workspace.pack()["phase"] == "unchanged"
        assert files(root / ".config-staging") == before


def test_unknown_service_state_uses_candidate(workspace, project):
    root, _ = project
    (root / "data/qqconf/services/web.json").unlink()
    edit(provider(workspace), lambda value: value["parameters"].update(temperature=0.2))
    assert workspace.pack()["destination"] == "candidate"


def test_unpack_uses_actual_source_and_keeps_pending_workspace_changes(workspace, project):
    root, service = project
    edit(provider(workspace), lambda value: value["parameters"].update(temperature=0.6))
    with service_guard(root, "web"):
        workspace.pack()
    draft = service.read()
    draft["document"]["providers"][0]["parameters"]["timeout_seconds"] = 60.0
    service.replace(draft["document"], draft["revision"])
    workspace.unpack()
    values = read_tree(workspace.storage.directory).snapshot["document"]["providers"][0][
        "parameters"
    ]
    assert values["temperature"] == 0.6
    assert values["timeout_seconds"] == 60.0
    assert workspace.storage.state()["base"] == content.read(root)


def test_discovery_rename_order_and_new_draft_references_are_atomic(workspace, project):
    root, service = project
    first = provider(workspace)
    value = decode(parse(first.read_bytes(), first.name))
    value["id"] = "beta"
    (first.parent / "new.toml").write_bytes(render_table(encode(value)))
    first.rename(first.with_name("renamed.toml"))
    order = workspace.storage.directory / "db/llm/order.toml"
    order.write_text('providers=["beta","alpha"]\n')
    scope = workspace.storage.directory / "db/scopes/groups/12345.toml"
    scope.parent.mkdir(parents=True)
    scope.write_text('id="12345"\nprovider_id="beta"\nmodel="first"\n')
    workspace.pack()
    assert [p["id"] for p in service.read()["document"]["providers"]] == ["beta", "alpha"]
    assert service.scope_settings.get_group_settings("12345").provider_id == "beta"
    assert service.read("published")["document"]["providers"] == []
    assert first.with_name("renamed.toml").exists()
    assert not list(first.parent.glob("*hash*"))


def test_assets_and_secrets_merge_by_field_without_expanding_references(workspace, project):
    root, _ = project
    local = workspace.storage.directory / ".env"
    local.write_text(local.read_text().replace("PORT=5000", "PORT=5100") + 'NEW="${PORT}"\n')
    (root / ".env").write_text(
        (root / ".env").read_text().replace("private-sentinel", "new-secret")
    )
    preview = json.dumps(workspace.refresh())
    assert "private-sentinel" not in preview
    assert "new-secret" not in preview
    assert "new-secret" in json.dumps(workspace.refresh(show_secrets=True))
    rules = workspace.storage.directory / "config/chat_rules.toml"
    edit(rules, lambda value: value["defaults"].update(chance=0.8))
    (root / "config/chat_rules.toml").write_text(
        "# source comment\n[defaults]\nweight=2\nchance=0.5\n"
    )
    workspace.pack()
    assert "PORT=5100" in (root / ".env").read_text()
    assert "${PORT}" in (root / ".env").read_text()
    assert "new-secret" in (root / ".env").read_text()
    assert "# keep" in (root / ".env").read_text()
    rules = parse((root / "config/chat_rules.toml").read_bytes(), "")
    assert rules["defaults"] == {"weight": 2, "chance": 0.8}


def test_runtime_skill_and_trace_files_are_not_managed(workspace, project):
    root, _ = project
    for name in (
        "skills/demo/SKILL.md",
        "data/pending_scheduled_messages.json",
        "data/trace.enabled",
        "prod/llbot-data/default_config.json",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private runtime bytes")
    workspace.unpack()
    for name in (
        "skills",
        "data/pending_scheduled_messages.json",
        "data/trace.enabled",
        "prod/llbot-data",
    ):
        assert not (workspace.storage.directory / name).exists()


def test_scope_game_and_recurring_configuration_keep_business_data(workspace, project):
    root, service = project
    runtime = (root / "data/config_runtime.db").read_bytes()
    (root / "data/llm.db").write_bytes(b"conversation sentinel")
    base = workspace.storage.directory
    scope = base / "db/scopes/private/67890.toml"
    scope.parent.mkdir(parents=True)
    scope.write_text('id="67890"\nhistory_limit=0\n')
    edit(base / "db/games/niuniu.toml", lambda value: value["groups"].update({"12345": "safe"}))
    (base / "data").mkdir(exist_ok=True)
    (base / "data/daily_summary_groups.json").write_text('{"enabled":["12345"]}\n')
    (base / "config/managed").mkdir(parents=True, exist_ok=True)
    (base / "config/managed/scheduled_messages.json").write_text('{"jobs":[]}\n')
    revision = service.read()["revision"]
    workspace.pack()
    assert service.read()["revision"] == revision
    assert service.scope_settings.get_group_settings("private:67890").history_limit == 0
    with sqlite3.connect(root / "config/managed/config.db") as connection:
        assert connection.execute("SELECT * FROM niuniu_group_text").fetchone() == ("12345", "safe")
    assert (root / "data/llm.db").read_bytes() == b"conversation sentinel"
    assert (root / "data/config_runtime.db").read_bytes() == runtime


def test_cli_module_outputs_human_and_json_without_hashes(workspace, project):
    root, _ = project
    from quickquip.config_workspace.__main__ import main

    assert main(["refresh", "--root", str(root), "--json"]) == 0
    result = subprocess.run(
        [sys.executable, "-m", "quickquip.config_workspace", "refresh", "--root", str(root)],
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "Services: stopped" in result.stdout
    assert "hash" not in result.stdout.lower()
    assert "private-sentinel" not in result.stdout


def test_offline_lease_prevents_service_start(project):
    root, _ = project
    with offline(root) as status:
        assert status == "stopped"
        with pytest.raises(ConfigError):
            with service_guard(root, "web"):
                pass
