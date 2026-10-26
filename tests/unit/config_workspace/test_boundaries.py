"""Text fidelity, secret previews, collection identities and project boundaries."""

from copy import deepcopy
import json
import os
import sqlite3

import pytest

from quickquip.configuration.errors import ConfigError
from quickquip.configuration import snapshot as content, comparison as planning, text
from quickquip.configuration.images import read_only
from quickquip.configuration.inventory import body, entry
from quickquip.config_workspace.layout import read_tree
from quickquip.configuration.merge import reconcile
from quickquip.config_workspace.service import Workspace

from .test_qqconf import files


@pytest.mark.parametrize(
    "identifiers",
    [("con", "foo"), ("a", "A"), ("CON.x", "item-CON.x"), ("x" * 100, "x" * 99 + "y")],
)
def test_portable_filenames_and_collisions_preserve_provider_order(project, identifiers):
    root, service = project
    draft = service.read()
    draft["document"]["providers"] = [
        {**deepcopy(draft["document"]["providers"][0]), "id": ident} for ident in identifiers
    ]
    service.replace(draft["document"], draft["revision"])
    work = Workspace(root=root)
    work.unpack()
    assert [
        p["id"] for p in read_tree(work.storage.directory).snapshot["document"]["providers"]
    ] == list(identifiers)
    assert work.pack()["phase"] == "unchanged"


def test_arbitrary_json_lists_are_atomic_and_nested_identity_is_not_hashed():
    base = [{"model": {"nested": 1}, "weight": 1}]
    left, right = deepcopy(base), deepcopy(base)
    left[0]["weight"] = 2
    right[0]["model"]["nested"] = 2
    conflicts = []
    assert (
        reconcile(
            base,
            left,
            right,
            path="document.providers.items.('alpha',).parameters.extra_body.models",
            conflicts=conflicts,
        )
        == left
    )
    assert len(conflicts) == 1


def test_yaml_and_dotenv_localized_field_merge_retains_comments():
    base = b'# deployment\nservice:\n  host: "localhost" # host\n  port: 5000 # port\n'
    left = base.replace(b"5000", b"5100")
    right = base.replace(b'"localhost"', b'"example.test"')
    snapshots = [
        dict(document={}, scopes={}, text_modes={}, files={"compose.yml": entry(raw)})
        for raw in (base, left, right)
    ]
    target, conflicts = planning.merge(*snapshots)
    assert not conflicts
    merged = body(target["files"]["compose.yml"])
    assert b'host: "example.test" # host' in merged
    assert b"port: 5100 # port" in merged
    assert merged.startswith(b"# deployment")
    raw = b'# bindings\nexport A="one" # first\nA=two\nB=${A}\n'
    values = text.parse(".env", raw)
    values["A"] = ["changed", "second"]
    result = text.render(".env", values, raw)
    assert text.parse(".env", result) == values
    assert b'export A="changed" # first' in result
    assert b"B=${A}" in result


def test_multiline_secret_and_url_are_hidden_even_outside_diff_context():
    original = "services:\n  bot:\n    environment:\n      PASSWORD: |\n" + "".join(
        f"        credential-line-{i}\n" for i in range(12)
    )
    changed = original.replace("credential-line-6", "replacement-credential")
    base = dict(
        document={}, scopes={}, text_modes={}, files={"compose.yml": entry(original.encode())}
    )
    target = {**base, "files": {"compose.yml": entry(changed.encode())}}
    result = planning.preview(base, target, base, target, [])
    assert "credential-line" not in json.dumps(result)
    assert "replacement-credential" not in json.dumps(result)
    assert "replacement-credential" in json.dumps(
        planning.preview(base, target, base, target, [], show_secrets=True)
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes and symlinks")
def test_workspace_is_private_and_configuration_db_redirect_is_rejected(workspace, project):
    root, _ = project
    assert workspace.storage.directory.stat().st_mode & 0o777 == 0o700
    db = root / "config/managed/config.db"
    external = root.parent / "external.db"
    db.rename(external)
    db.symlink_to(external)
    before = external.read_bytes()
    with pytest.raises(ConfigError, match="redirected"):
        workspace.refresh()
    with pytest.raises(ConfigError, match="redirected"):
        workspace.pack()
    assert external.read_bytes() == before


def test_domain_invalid_admin_config_and_missing_last_persona_are_rejected(project):
    root, _ = project
    snapshot = content.read(root)
    snapshot["files"]["config/admins.toml"] = entry(b'global_admins = "12345"\n')
    with pytest.raises(ConfigError, match="domain configuration"):
        content.validate(snapshot)
    snapshot["files"].pop("config/admins.toml")
    snapshot["document"]["settings"]["runtime"]["default_persona"] = "deleted"
    with pytest.raises(ConfigError, match="persona is missing"):
        content.validate(snapshot)


def test_readonly_snapshot_includes_committed_wal_without_source_mutation(project):
    root, _ = project
    path = root / "config/managed/config.db"
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("INSERT INTO niuniu_group_text VALUES('12345','safe')")
        connection.commit()
        before = files(root)
        with read_only(path) as snapshot:
            assert snapshot.execute("SELECT text_mode FROM niuniu_group_text").fetchone() == (
                "safe",
            )
        assert files(root) == before
    finally:
        connection.close()


def test_unpack_refuses_partial_source_before_creating_new_workspace(workspace, project):
    root, _ = project
    marker = root / "data/qqconf/active.json"
    marker.write_text("{}")
    other = root / ".other-workspace"
    with pytest.raises(ConfigError, match="pack before unpacking"):
        Workspace(root=root, directory=other).unpack()
    assert not other.exists()


def test_duplicate_candidate_target_failure_retains_old_candidate(workspace, project, monkeypatch):
    from pathlib import Path
    from .test_qqconf import edit, provider

    root, _ = project
    (root / "data/qqconf/services/web.json").unlink()
    edit(provider(workspace), lambda value: value["parameters"].update(temperature=0.2))
    workspace.pack()
    candidate = root / ".config-staging"
    (candidate / ".env").write_text("PORT=5900\n")
    before = files(candidate)
    rename = Path.rename

    def fail_publish(self, destination):
        if self.name == ".config-staging.new":
            raise OSError("synthetic candidate switch failure")
        return rename(self, destination)

    monkeypatch.setattr(Path, "rename", fail_publish)
    with pytest.raises(OSError, match="switch failure"):
        workspace.pack()
    assert files(candidate) == before
    assert not workspace._pending()


def test_unpack_can_export_invalid_text_configuration_for_workspace_repair(project):
    root, _ = project
    (root / "config/admins.toml").write_text('global_admins = "12345"\n')
    work = Workspace(root=root)
    work.unpack()
    (work.storage.directory / "config/admins.toml").write_text('global_admins = ["12345"]\n')
    work.pack()
    assert (root / "config/admins.toml").read_text() == 'global_admins = ["12345"]\n'


def test_recurring_jobs_merge_by_identity_and_rule_switch_types_are_checked(project):
    root, _ = project
    snapshot = content.read(root)
    name = "config/managed/scheduled_messages.json"
    jobs = [
        dict(id="one", cron="0 8 * * *", group_ids=["12345"], message="morning"),
        dict(id="two", cron="0 9 * * *", group_ids=["12345"], message="hello"),
    ]
    snapshots = [deepcopy(snapshot) for _ in range(3)]
    for value in snapshots:
        value["files"][name] = entry(json.dumps(dict(jobs=jobs)).encode())
    left, right = deepcopy(jobs), deepcopy(jobs)
    left[0]["message"] = "updated morning"
    right[1]["cron"] = "0 10 * * *"
    snapshots[1]["files"][name] = entry(json.dumps(dict(jobs=left)).encode())
    snapshots[2]["files"][name] = entry(json.dumps(dict(jobs=right)).encode())
    merged, conflicts = planning.merge(*snapshots)
    assert not conflicts
    content.validate(merged)
    result = json.loads(body(merged["files"][name]))["jobs"]
    assert result[0]["message"] == "updated morning"
    assert result[1]["cron"] == "0 10 * * *"
    merged["files"]["data/rule_switch.json"] = entry(b'{"12345": 3}')
    with pytest.raises(ConfigError, match="rule names"):
        content.validate(merged)


def test_delete_modify_conflict_is_atomic_and_source_preference_keeps_other_edits(
    workspace, project
):
    from .test_qqconf import edit, provider

    root, service = project
    path = provider(workspace)
    edit(path, lambda value: value["parameters"].update(temperature=0.2))
    draft = service.read()
    draft["document"]["providers"][0]["models"][1]["context_window"] = 64000
    service.replace(draft["document"], draft["revision"])
    edit(path, lambda value: value["models"].pop())
    assert workspace.refresh()["conflicts"]
    before = content.read(root)
    with pytest.raises(ConfigError):
        workspace.pack()
    assert content.read(root) == before
    workspace.pack(prefer="source")
    result = service.read()["document"]["providers"][0]
    assert result["parameters"]["temperature"] == 0.2
    assert result["models"][1]["context_window"] == 64000


@pytest.mark.parametrize("exported", [False, True])
def test_target_env_validates_references_without_changing_process_environment(
    project, monkeypatch, exported
):
    from quickquip.common.config_utils import expand_env_value

    root, _ = project
    url, persona = "QQCONF_TEST_GENERATION_URL", "QQCONF_TEST_PERSONA_ID"
    for key in (url, persona):
        if exported:
            monkeypatch.setenv(key, "host-environment-value")
        else:
            monkeypatch.delenv(key, raising=False)
    snapshot = content.read(root)
    raw_env = f"{url}=https://generation.test/v1\n{persona}=target-persona\n".encode()
    snapshot["files"][".env"] = entry(raw_env)
    generation = b"""[[image.providers]]
id = "images"
protocol = "openai_images"
base_url = "${QQCONF_TEST_GENERATION_URL}"
api_key_env = "SYNTHETIC_API_KEY"
"""
    snapshot["files"]["config/generation.toml"] = entry(generation)
    snapshot["files"]["config/personas/example.toml"] = entry(b'id="${QQCONF_TEST_PERSONA_ID}"\n')
    snapshot["document"]["settings"]["runtime"]["default_persona"] = "target-persona"
    result = content.validate(snapshot)
    assert body(result["files"]["config/generation.toml"]) == generation
    assert body(result["files"][".env"]) == raw_env
    expected = "host-environment-value" if exported else ""
    assert expand_env_value("${" + persona + "}") == expected
    snapshot["files"][".env"] = entry(f"{url}=\n{persona}=target-persona\n".encode())
    with pytest.raises(ConfigError, match="domain configuration"):
        content.validate(snapshot)
    assert expand_env_value("${" + persona + "}") == expected


@pytest.mark.parametrize("remove", [False, True])
def test_install_keeps_external_edit_made_while_other_files_are_writing(
    tmp_path, monkeypatch, remove
):
    from quickquip.configuration import files as storage

    before = {name: entry(b"original") for name in ("config/a.toml", "config/b.toml")}
    storage.install(tmp_path, {}, before)
    after = {"config/a.toml": entry(b"target")}
    if not remove:
        after["config/b.toml"] = entry(b"target")
    write = storage.durable_write

    def concurrent_edit(path, value):
        write(path, value)
        if path.name == "a.toml":
            (tmp_path / "config/b.toml").write_bytes(b"external editor")

    monkeypatch.setattr(storage, "durable_write", concurrent_edit)
    # Deletions run first, so use two removed files to expose a mid-delete edit as well.
    if remove:
        from pathlib import Path

        unlink = Path.unlink
        after = {}

        def concurrent_delete(path, *args, **kwargs):
            result = unlink(path, *args, **kwargs)
            if path.name == "a.toml":
                (tmp_path / "config/b.toml").write_bytes(b"external editor")
            return result

        monkeypatch.setattr(Path, "unlink", concurrent_delete)
    with pytest.raises(ConfigError, match="External edit"):
        storage.install(tmp_path, before, after)
    assert (tmp_path / "config/b.toml").read_bytes() == b"external editor"
