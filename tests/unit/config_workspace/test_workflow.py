from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys

import pytest

from quickquip.config_sync.bundle import digest
from quickquip.config_workspace.codec import render_table
from quickquip.config_workspace.layout import read_tree
from quickquip.config_workspace.service import Workspace, validate_offline
from quickquip.llm.config_errors import ConfigError
from tests.unit.config_workspace.conftest import change_source, edit_value, provider_file


def execute(workspace, action="refresh", **kwargs):
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


def test_comment_only_edits_do_not_change_database_or_disappear_during_refresh(workspace):
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
        workspace.execute("refresh", plan["plan_hash"])
    assert read_tree(workspace.storage.directory).files == before_files
    overwrite = workspace.plan(overwrite=True)
    assert overwrite["discarded_units"] == ["document"]
    execute(workspace, overwrite=True)
    assert (
        source.service.read()["document"]["providers"][0]["parameters"]["timeout_seconds"] == 35.0
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
        workspace.execute("refresh", plan["plan_hash"])
    assert error.value.code == "revision_conflict"
    assert workspace.storage.active() is None


def test_projection_mismatch_is_rejected_before_export(workspace, source):
    with source.service.store.connect(write=True) as connection:
        connection.execute("UPDATE providers SET position=99")
    with pytest.raises(ConfigError) as error:
        workspace.plan()
    assert error.value.code == "projection_mismatch"


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
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[3] / "src")},
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


@pytest.mark.parametrize("inherited", [False, True])
def test_cli_uses_selected_root_dotenv_preserving_references_and_environment_precedence(
    workspace, tmp_path, inherited
):
    root = workspace.endpoint.root
    asset = b'''[image]
enabled = false
default_model = "image"
[[image.providers]]
id = "images"
protocol = "openai_images"
base_url = "${TEST_WORKSPACE_BASE}"
api_key_env = "TEST_WORKSPACE_SECRET"
[[image.providers.models]]
id = "image"
model = "image"
'''
    (root / "config/generation.toml").write_bytes(asset)
    file_url = "" if inherited else "https://file.invalid/v1"
    secret = "synthetic-workspace-dotenv-secret"
    (root / ".env").write_text(
        f'TEST_WORKSPACE_BASE="{file_url}"\nTEST_WORKSPACE_SECRET="{secret}"\n'
    )
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[3] / "src")}
    env.pop("TEST_WORKSPACE_BASE", None)
    env.pop("TEST_WORKSPACE_SECRET", None)
    if inherited:
        env["TEST_WORKSPACE_BASE"] = "https://inherited.invalid/v1"
    directory = tmp_path / "dotenv-workspace"
    for command in ("init", "validate"):
        result = subprocess.run(
            [
                sys.executable, "-m", "quickquip.config_workspace", "--root", str(root),
                command, str(directory),
            ],
            env=env,
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr.decode()
        assert secret.encode() not in result.stdout + result.stderr
    assert (directory / "assets/config/generation.toml").read_bytes() == asset
    for path in directory.rglob("*"):
        if path.is_file():
            contents = path.read_bytes()
            assert secret.encode() not in contents
            assert b"https://file.invalid/v1" not in contents
            assert b"https://inherited.invalid/v1" not in contents
