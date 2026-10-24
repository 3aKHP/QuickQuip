from copy import deepcopy
import shutil

import pytest

from quickquip.config_workspace.codec import render_table
from quickquip.config_workspace.layout import read_tree
from quickquip.llm.config_errors import ConfigError


@pytest.mark.parametrize(
    "bad",
    [
        "../outside.toml",
        "providers/../outside.toml",
        "providers/CON.toml",
        "providers/a\\b.toml",
        "providers/a:.toml",
        "providers/trailing. .toml",
        1,
    ],
)
def test_unsafe_manifest_paths_are_rejected(workspace, bad):
    tree = read_tree(workspace.storage.directory)
    manifest = deepcopy(tree.manifest)
    manifest["providers"][0] = bad
    (workspace.storage.directory / "workspace.toml").write_bytes(render_table(manifest))
    with pytest.raises(ConfigError):
        workspace.validate()


def test_symlink_cannot_export_or_import_an_unmanaged_file(workspace, tmp_path):
    path = workspace.storage.directory / "assets/config/admins.toml"
    outside = tmp_path / "outside.toml"
    outside.write_text("# outside\n")
    path.unlink()
    try:
        path.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symbolic links requires privileges on this platform")
    with pytest.raises(ConfigError):
        workspace.validate()
    assert outside.read_text() == "# outside\n"


def test_case_collisions_are_rejected_before_files_are_installed(workspace):
    tree = read_tree(workspace.storage.directory)
    manifest = deepcopy(tree.manifest)
    name = manifest["providers"][0]
    manifest["providers"].append("providers/" + name.split("/", 1)[1][:-5].upper() + ".toml")
    (workspace.storage.directory / "workspace.toml").write_bytes(render_table(manifest))
    with pytest.raises(ConfigError):
        workspace.validate()


def test_init_never_overwrites_an_existing_workspace(workspace):
    before = read_tree(workspace.storage.directory).files
    with pytest.raises(ConfigError) as error:
        workspace.initialize()
    assert error.value.code == "workspace_exists"
    assert read_tree(workspace.storage.directory).files == before


@pytest.mark.parametrize("folder", ["config/personas", "data/export", "llm_about/export"])
def test_dot_segments_cannot_bypass_active_directory_boundaries(workspace, folder):
    from quickquip.config_workspace.service import Workspace

    root = workspace.endpoint.root
    (root / "scratch").mkdir()
    with pytest.raises(ConfigError):
        Workspace(root / "scratch/.." / folder, root).initialize()
    assert not (root / folder / "workspace.toml").exists()


def test_reader_bounds_total_workspace_bytes(workspace, monkeypatch):
    from quickquip.config_workspace import layout

    monkeypatch.setattr(layout, "MAX_TREE_BYTES", 128)
    with pytest.raises(ConfigError) as error:
        workspace.validate()
    assert error.value.code == "body_too_large"


def test_alias_of_active_data_directory_cannot_receive_a_workspace(workspace, tmp_path):
    from quickquip.config_workspace.service import Workspace

    root = workspace.endpoint.root
    actual = tmp_path / "actual-data"
    shutil.move(root / "data", actual)
    try:
        (root / "data").symlink_to(actual, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symbolic links requires privileges on this platform")
    with pytest.raises(ConfigError):
        Workspace(actual / "export", root).initialize()
    assert not (actual / "export").exists()


def test_symlinked_private_state_is_rejected(workspace, tmp_path):
    other = tmp_path / "other-state"
    other.mkdir()
    redirected = workspace.storage.directory / ".quickquip/operations"
    try:
        redirected.symlink_to(other, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symbolic links requires privileges on this platform")
    with pytest.raises(ConfigError):
        workspace.storage.save({"id": "a" * 32})
    assert not list(other.iterdir())


@pytest.mark.parametrize("command", ["resume", "recover"])
def test_case_only_asset_rename_can_refresh_and_restore(workspace, source, monkeypatch, command):
    from quickquip.config_workspace.service import Workspace
    from quickquip.config_workspace.storage import Storage

    folder = source.root / "config/personas"
    folder.mkdir()
    old = folder / "alpha.toml"
    old.write_text('id = "alpha"\ndisplay_name = "Test"\nsystem_prompt = "Test"\n')
    workspace.execute("refresh", workspace.plan(action="refresh")["plan_hash"])
    before = read_tree(workspace.storage.directory).files
    old.rename(folder / "Alpha.toml")
    version = source.version()
    original = Storage.write

    def interrupt_state(self, name, value):
        if name == "state.json":
            raise OSError("interrupted renamed asset receipt")
        return original(self, name, value)

    with monkeypatch.context() as patch:
        patch.setattr(Storage, "write", interrupt_state)
        with pytest.raises(OSError):
            workspace.execute("refresh", workspace.plan(action="refresh")["plan_hash"])
    operation = workspace.storage.active()
    assert operation
    resumed = Workspace(workspace.storage.directory, source.root)
    assert getattr(resumed, command)(operation)["phase"] == (
        "confirmed" if command == "resume" else "recovered"
    )
    assert resumed.storage.active() is None
    files = read_tree(resumed.storage.directory).files
    if command == "resume":
        assert "assets/config/personas/Alpha.toml" in files
        assert "assets/config/personas/alpha.toml" not in files
        assert read_tree(resumed.storage.directory).bundle == source.capture()["bundle"]
    else:
        assert files == before
    assert source.version() == version
