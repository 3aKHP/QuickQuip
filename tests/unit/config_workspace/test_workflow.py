from copy import deepcopy
import os
import subprocess
import sys

import pytest

from quickquip.config_sync.bundle import digest
from quickquip.config_workspace.codec import render_table
from quickquip.config_workspace.layout import read_tree
from quickquip.config_workspace.service import Workspace, validate_offline
from quickquip.llm.config_errors import ConfigError
from tests.unit.config_workspace.conftest import change_source, edit_value, provider_file


def execute(workspace, action="pack", **kwargs):
    plan = workspace.plan(action=action, overwrite=kwargs.get("overwrite", False))
    return workspace.execute(action, plan["plan_hash"], **kwargs)


def test_full_bundle_noop_preserves_assets_types_order_and_does_not_create_revision(workspace):
    before = workspace.endpoint.capture()
    files = read_tree(workspace.storage.directory).files
    assert digest(read_tree(workspace.storage.directory).bundle) == digest(before["bundle"])
    assert execute(workspace)["phase"] == "unchanged"
    assert execute(workspace)["phase"] == "unchanged"
    assert workspace.endpoint.version() == before["version"]
    assert read_tree(workspace.storage.directory).files == files
    assert files["assets/config/admins.toml"] == b"# original bytes\r\n"


def test_pack_updates_only_draft_and_does_not_move_sync_peer_baseline(workspace):
    endpoint = workspace.endpoint
    peer = "a" * 32
    before = endpoint.capture()
    endpoint.state.acknowledge(peer, before["bundle"], "b" * 32)
    edit_value(
        workspace, provider_file(workspace), lambda p: p["parameters"].update(timeout_seconds=31.0)
    )
    result = execute(workspace)
    assert result["phase"] == "confirmed"
    after = endpoint.capture()
    assert after["version"]["draft_revision"] == before["version"]["draft_revision"] + 1
    assert after["published"] == before["published"]
    assert digest(after["bundle"]) == workspace.storage.state()["base_hash"]
    assert endpoint.state.baseline(peer) == before["bundle"]
    assert endpoint.state.read("maintenance.json") is None
    assert "peer" not in endpoint.state.operation(result["operation"])


def test_pack_can_explicitly_clear_alias_and_pricing_arrays(workspace):
    edit_value(workspace, provider_file(workspace), lambda p: p.update(aliases=[]))
    edit_value(workspace, "pricing.toml", lambda prices: [])
    execute(workspace)
    document = workspace.endpoint.service.read()["document"]
    assert document["providers"][0]["aliases"] == []
    assert document["pricing"] == []


def test_refresh_imports_source_values_preserving_comments_and_leaves_source_untouched(
    workspace, source
):
    name = provider_file(workspace)
    path = workspace.storage.directory / name
    path.write_bytes(b"# local explanation\n" + path.read_bytes())
    change_source(source, 35.0)
    version = source.version()
    execute(workspace, "refresh")
    assert b"# local explanation\n" in path.read_bytes()
    assert source.version() == version
    assert read_tree(workspace.storage.directory).bundle == source.capture()["bundle"]


def test_comment_only_edits_do_not_change_database_or_disappear_during_pack(workspace):
    path = workspace.storage.directory / provider_file(workspace)
    path.write_bytes(b"# keep this note\n" + path.read_bytes())
    before = workspace.endpoint.version()
    assert execute(workspace)["phase"] == "unchanged"
    assert workspace.endpoint.version() == before
    assert path.read_bytes().startswith(b"# keep this note")


def test_database_refresh_can_clear_a_nested_extra_body_object(workspace, source):
    state = source.service.read()
    state["document"]["providers"][0]["parameters"]["extra_body"]["empty_parent"] = {"child": {}}
    source.service.replace(state["document"], state["revision"])
    execute(workspace, "refresh")
    state = source.service.read()
    state["document"]["providers"][0]["parameters"]["extra_body"]["empty_parent"] = {}
    source.service.replace(state["document"], state["revision"])
    execute(workspace, "refresh")
    tree = read_tree(workspace.storage.directory)
    assert tree.bundle == source.capture()["bundle"]
    assert tree.bundle["document"]["providers"][0]["parameters"]["extra_body"]["empty_parent"] == {}


def test_refresh_retains_workspace_change_on_separate_asset(workspace, source):
    path = workspace.storage.directory / "assets/config/admins.toml"
    path.write_bytes(b"# local asset edit\n")
    change_source(source, 35.0)
    execute(workspace, "refresh")
    assert path.read_bytes() == b"# local asset edit\n"
    assert workspace.status()["dirty"] is True
    assert workspace.storage.state()["base_hash"] == digest(source.capture()["bundle"])


def test_document_conflicts_are_not_field_merged_and_explicit_overwrite_is_directional(
    workspace, source
):
    edit_value(
        workspace, provider_file(workspace), lambda p: p["parameters"].update(timeout_seconds=31.0)
    )
    change_source(source, 35.0)
    before_files = read_tree(workspace.storage.directory).files
    plan = workspace.plan()
    assert plan["conflicts"] == ["document"]
    with pytest.raises(ConfigError, match="same unit"):
        workspace.execute("pack", plan["plan_hash"])
    assert read_tree(workspace.storage.directory).files == before_files
    overwrite = workspace.plan(overwrite=True)
    assert overwrite["discarded_units"] == ["document"]
    execute(workspace, overwrite=True)
    assert (
        source.service.read()["document"]["providers"][0]["parameters"]["timeout_seconds"] == 31.0
    )
    edit_value(
        workspace, provider_file(workspace), lambda p: p["parameters"].update(timeout_seconds=39.0)
    )
    execute(workspace, "refresh", overwrite=True)
    assert not workspace.status()["dirty"]


@pytest.mark.parametrize("edit", ["source", "comment", "asset", "sql"])
def test_expected_plan_rejects_changes_after_preview(workspace, source, edit):
    plan = workspace.plan()
    if edit == "source":
        change_source(source, 40.0)
    elif edit == "comment":
        path = workspace.storage.directory / provider_file(workspace)
        path.write_bytes(b"# racing edit\n" + path.read_bytes())
    elif edit == "asset":
        (source.root / "config/admins.toml").write_bytes(b"# source asset changed\n")
    else:
        from quickquip.llm.config_store import dumps, project_document

        doc = source.service.read()["document"]
        doc["providers"][0]["parameters"]["timeout_seconds"] = 44.0
        with source.service.store.connect(write=True) as connection:
            connection.execute("UPDATE config_meta SET document=?", (dumps(doc),))
            project_document(connection, doc)
    with pytest.raises(ConfigError) as error:
        workspace.execute("pack", plan["plan_hash"])
    assert error.value.code == "revision_conflict"
    assert workspace.storage.active() is None


def test_projection_mismatch_is_rejected_before_export(workspace, source):
    with source.service.store.connect(write=True) as connection:
        connection.execute("UPDATE providers SET position=99")
    with pytest.raises(ConfigError) as error:
        workspace.plan()
    assert error.value.code == "projection_mismatch"


def test_assets_require_stopped_services_and_are_installed_without_publishing(workspace):
    endpoint = workspace.endpoint
    path = workspace.storage.directory / "assets/config/admins.toml"
    path.write_bytes(b"# new administrator explanation\n")
    plan = workspace.plan()
    with pytest.raises(ConfigError) as error:
        workspace.execute("pack", plan["plan_hash"])
    assert error.value.code == "services_running"
    before = endpoint.version()
    execute(workspace, services_stopped=True)
    assert (endpoint.root / "config/admins.toml").read_bytes() == path.read_bytes()
    assert endpoint.version()["published_revision"] == before["published_revision"]
    assert endpoint.version()["draft_revision"] == before["draft_revision"]


def test_fresh_bot_heartbeat_prevents_file_install_even_with_operator_flag(workspace):
    path = workspace.storage.directory / "assets/config/admins.toml"
    path.write_bytes(b"# new\n")
    workspace.endpoint.service.register_bot_boot("active", 1)
    with pytest.raises(ConfigError) as error:
        execute(workspace, services_stopped=True)
    assert error.value.code == "services_running"


def test_duplicate_registration_missing_files_and_unsupported_format_are_rejected(workspace):
    manifest_path = workspace.storage.directory / "workspace.toml"
    original = manifest_path.read_bytes()
    tree = read_tree(workspace.storage.directory)
    for mutation in (
        lambda m: m["providers"].append(m["providers"][0]),
        lambda m: m.update(format_version=99),
        lambda m: m["providers"].append("providers/missing.toml"),
    ):
        manifest = deepcopy(tree.manifest)
        mutation(manifest)
        manifest_path.write_bytes(render_table(manifest))
        with pytest.raises(ConfigError):
            validate_offline(workspace.storage.directory)
    manifest_path.write_bytes(original)


def test_unregistered_toml_is_rejected_but_editor_backup_is_not_packed(workspace):
    path = workspace.storage.directory / "providers/extra.toml"
    path.write_text("value = 1\n")
    with pytest.raises(ConfigError):
        workspace.validate()
    path.rename(path.with_suffix(".toml.bak"))
    assert workspace.validate()["valid"]


def test_offline_validation_and_cli_utf8_do_not_require_original_root(workspace):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "quickquip.config_workspace",
            "--root",
            str(workspace.endpoint.root / "missing"),
            "validate",
            str(workspace.storage.directory),
        ],
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert b'"valid": true' in result.stdout
    if os.name != "nt":
        assert workspace.storage.directory.stat().st_mode & 0o077 == 0
        assert (workspace.storage.private / "state.json").stat().st_mode & 0o077 == 0


def test_workspaces_cannot_overwrite_active_config_or_bind_another_root(workspace, tmp_path):
    with pytest.raises(ConfigError):
        Workspace(workspace.endpoint.root / "config/export", workspace.endpoint.root)
    with pytest.raises(ConfigError):
        Workspace(workspace.storage.directory, tmp_path / "different").plan()


def test_published_persona_asset_is_protected_before_any_pack_write(workspace, tmp_path):
    from quickquip.llm.config_document import validate_document
    from quickquip.llm.config_service import ConfigService

    root = tmp_path / "published-project"
    personas = root / "config/personas"
    personas.mkdir(parents=True)
    for name in ("base", "other"):
        (personas / (name + ".toml")).write_text(
            f'id = "{name}"\ndisplay_name = "Test {name}"\nsystem_prompt = "Test"\n',
            encoding="utf-8",
        )
    document = workspace.endpoint.service.read()["document"]
    document["settings"]["runtime"].update(
        enabled=True, default_provider="alpha", default_persona="base"
    )
    service = ConfigService(root / "data/llm_config.db")
    service.store.create(validate_document(document, config_dir=root / "config"))
    value = Workspace(tmp_path / "published-workspace", root)
    value.initialize()
    tree = read_tree(value.storage.directory)
    entry = next(e for e in tree.manifest["settings"] if e["id"] == "runtime")
    edit_value(value, entry["file"], lambda p: p.update(default_persona="other"))
    manifest = deepcopy(tree.manifest)
    manifest["assets"].remove("config/personas/base.toml")
    (value.storage.directory / "assets/config/personas/base.toml").unlink()
    (value.storage.directory / "workspace.toml").write_bytes(render_table(manifest))
    plan = value.plan()
    before = value.endpoint.version()
    with pytest.raises(ConfigError) as error:
        value.execute("pack", plan["plan_hash"], services_stopped=True)
    assert error.value.code == "missing_persona"
    assert value.endpoint.version() == before
    assert value.storage.active() is None


def test_workspace_pack_is_visible_to_existing_sync_plan_and_push(workspace, tmp_path, monkeypatch):
    from quickquip.config_sync.client import Synchronizer
    from quickquip.config_sync.endpoint import Endpoint
    from quickquip.llm.config_service import ConfigService
    from tests.unit.config_sync.test_sync import LocalRemote

    root = tmp_path / "remote"
    (root / "config").mkdir(parents=True)
    ConfigService(root / "data/llm_config.db").initialize()
    monkeypatch.setenv("TEST_API_KEY", "synthetic-test-key")
    sync = Synchronizer(workspace.endpoint, LocalRemote(Endpoint(root)))
    assert sync.run(initial="local")["phase"] == "confirmed"
    peer = sync.remote.endpoint.state.identity()["id"]
    baseline = deepcopy(workspace.endpoint.state.baseline(peer))
    edit_value(
        workspace, provider_file(workspace), lambda p: p["parameters"].update(timeout_seconds=47.0)
    )
    execute(workspace)
    assert workspace.endpoint.state.baseline(peer) == baseline
    result, *_ = sync.preview()
    assert not result["conflicts"]
    assert any(change["unit"] == "document" and change["remote"] for change in result["changes"])
    assert sync.run()["phase"] == "confirmed"
    assert (
        sync.remote.endpoint.capture("published")["bundle"]
        == workspace.endpoint.capture()["bundle"]
    )
