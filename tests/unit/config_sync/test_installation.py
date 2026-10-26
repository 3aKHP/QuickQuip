"""Receiver transactions preserve drafts, stopped state and unrelated runtime progress."""

from copy import deepcopy
import uuid

import pytest

from quickquip.config_sync.capture import read
from quickquip.config_sync.installation import Installation
from quickquip.configuration.activity import service_guard
from quickquip.configuration.errors import ConfigError
from quickquip.configuration.inventory import entry
from quickquip.llm.config_service import ConfigService


@pytest.fixture
def receiver(tmp_path):
    service = ConfigService(tmp_path / "config/managed/config.db")
    service.initialize()
    (tmp_path / ".env").write_text(
        "QUICKQUIP_DEPLOY_LOCATION=local\nQUICKQUIP_DEPLOY_RUNTIME=source\n", encoding="utf-8"
    )
    return Installation(tmp_path), service


def test_offline_install_rebases_draft_and_preserves_history_and_runtime_on_restore(receiver):
    install, service = receiver
    draft = service.read()["document"]
    draft["settings"]["runtime"]["memory_limit"] = 17
    service.replace(draft, 1, note="unfinished edits")
    before = read(install.layout, "published")
    target = deepcopy(before["snapshot"])
    target["document"]["settings"]["runtime"]["history_limit"] = 19
    target["text_modes"] = {"123456789": "safe"}
    target["files"]["config/admins.toml"] = entry(b"superusers=[]\n")
    operation = uuid.uuid4().hex
    install.prepare(operation, before, target, publish=True)
    install.install(operation)
    install.verify(operation)
    assert service.read("published")["document"] == target["document"]
    assert service.read()["document"]["settings"]["runtime"]["memory_limit"] == 17
    assert service.read()["document"]["settings"]["runtime"]["history_limit"] == 19
    # Runtime task history must survive recovery, including records written after installation.
    with service.execution.connect(write=True) as connection:
        connection.execute(
            "INSERT INTO config_operations(id,request_id,kind,target_revision,status,stage,payload,"
            "created_at,updated_at) VALUES('other','other','probe',1,"
            "'succeeded','finished','{}',1,1)"
        )
    install.restore(operation)
    install.recovered(operation)
    assert read(install.layout, "published")["snapshot"] == before["snapshot"]
    assert service.read()["document"] == before["draft"]
    assert service.tasks.get("other")["status"] == "succeeded"
    with service.store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM config_revisions").fetchone()[0] > 2
    assert not (install.root / "data/config-sync/maintenance.json").exists()


def test_retry_after_files_written_and_pin_saved_is_idempotent(receiver, monkeypatch):
    install, service = receiver
    before = read(install.layout, "published")
    target = deepcopy(before["snapshot"])
    target["document"]["settings"]["runtime"]["history_limit"] = 19
    target["files"]["config/admins.toml"] = entry(b"superusers=[]\n")
    operation = uuid.uuid4().hex
    install.prepare(operation, before, target, publish=True)
    original = ConfigService.publish_offline

    def interrupted(*args, **kwargs):
        raise OSError("interrupted before publication")

    monkeypatch.setattr(ConfigService, "publish_offline", interrupted)
    with pytest.raises(OSError):
        install.install(operation)
    with pytest.raises(ConfigError, match="Repeat qqsync"):
        with service_guard(install.root, "bot"):
            pass
    monkeypatch.setattr(ConfigService, "publish_offline", original)
    install.install(operation)
    install.install(operation)
    install.verify(operation)
    install.confirm(operation)
    assert read(install.layout, "published")["snapshot"] == target
    assert len(service.tasks.list()) == 1
    with service_guard(install.root, "bot"):
        pass


def test_independent_draft_conflict_is_reported_before_any_file_write(receiver):
    install, service = receiver
    draft = service.read()["document"]
    draft["settings"]["runtime"]["history_limit"] = 31
    service.replace(draft, 1)
    before = read(install.layout, "published")
    target = deepcopy(before["snapshot"])
    target["document"]["settings"]["runtime"]["history_limit"] = 19
    with pytest.raises(ConfigError) as error:
        install.prepare(uuid.uuid4().hex, before, target, publish=True)
    assert error.value.code == "draft_conflict"
    assert read(install.layout, "published") == before
    assert not (install.root / "data/config-sync/maintenance.json").exists()
