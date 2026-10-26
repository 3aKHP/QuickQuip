"""Offline publication preserves drafts, revision identity and truthful load state."""

from copy import deepcopy

import pytest

from quickquip.configuration.activity import service_guard, stopped_service
from quickquip.configuration.errors import ConfigError
from quickquip.configuration import images
from quickquip.llm.config_service import ConfigService


@pytest.fixture
def deployment(tmp_path):
    service = ConfigService(tmp_path / "config/managed/config.db")
    service.initialize()
    return tmp_path, service


def test_offline_publication_requires_a_live_exclusive_bot_lease(deployment):
    root, service = deployment
    with pytest.raises(ConfigError, match="lease"):
        service.publish_offline(1, "offline", None)
    with service_guard(root, "bot"):
        with pytest.raises(ConfigError, match="Stop"):
            with stopped_service(root, "bot"):
                pass
    with stopped_service(root, "bot") as stopped:
        with pytest.raises(ConfigError, match="lease"):
            with service_guard(root, "bot"):
                pass
    with pytest.raises(ConfigError, match="lease"):
        service.publish_offline(1, "expired", stopped)
    assert service.read("published")["revision"] == 1
    assert service.tasks.list() == []


def test_offline_publication_keeps_independent_draft_and_last_actual_load(deployment):
    root, service = deployment
    published = service.read("published")["document"]
    draft = deepcopy(published)
    draft["settings"]["runtime"]["memory_limit"] = 12
    service.replace(draft, 1, note="unfinished model edits")
    target = deepcopy(published)
    target["settings"]["runtime"]["history_limit"] = 21
    draft["settings"]["runtime"]["history_limit"] = 21
    prepared = service.prepare_deployment(target, 2, draft=draft)
    service.register_bot_boot("previous-boot", 1)
    with stopped_service(root, "bot") as stopped:
        result = service.publish_offline(prepared["revision"], "deployment-one", stopped)
        assert service.publish_offline(prepared["revision"], "deployment-one", stopped) == result
    assert result == {"published_revision": prepared["revision"], "loaded": False}
    assert service.read("published")["document"] == target
    assert service.read()["document"] == draft
    status = service.status()
    assert status["draft_version"]["note"] == "unfinished model edits"
    assert status["published_version"]["note"] == "qqsync"
    assert status["bot"]["loaded_revision"] == 1
    assert status["bot"]["heartbeat_at"] == 0
    assert status["bot"]["boot_id"] != "previous-boot"
    assert len(service.tasks.list()) == 1
    with pytest.raises(ConfigError) as error:
        service.assert_bot_boot("previous-boot")
    assert error.value.code == "runtime_superseded"


def test_edit_after_pinning_a_deployment_does_not_reuse_its_revision(deployment, tmp_path):
    root, service = deployment
    target = service.read()["document"]
    target["settings"]["runtime"]["history_limit"] = 20
    draft = deepcopy(target)
    draft["settings"]["runtime"]["memory_limit"] = 14
    service.replace(draft, 1)
    prepared = service.prepare_deployment(target, 2, draft=draft)
    assert service.read()["revision"] == 2 < prepared["revision"]
    with stopped_service(root, "bot") as stopped:
        service.publish_offline(prepared["revision"], "pinned", stopped)
    draft["settings"]["runtime"]["max_prompt_chars"] = 5000
    candidate = tmp_path / "prepared.db"
    images.prepare(service.path, candidate, {"document": draft, "scopes": {}, "text_modes": {}})
    with images.read_only(candidate) as connection:
        assert connection.execute("SELECT draft_revision FROM config_meta").fetchone()[0] > (
            prepared["revision"]
        )
    updated = service.replace(draft, 2)
    assert updated["revision"] > prepared["revision"]
    assert service.read(prepared["revision"])["document"] == target
    assert service.read("published")["document"] == target


def test_offline_publication_preserves_an_independent_pending_apply(deployment):
    root, service = deployment
    target = service.read()["document"]
    target["settings"]["runtime"]["history_limit"] = 22
    prepared = service.prepare_deployment(target, 1)
    queued = service.apply(prepared["draft_revision"], "web-admin-request")
    with stopped_service(root, "bot") as stopped:
        with pytest.raises(ConfigError, match="pending"):
            service.publish_offline(prepared["revision"], "deployment", stopped)
    assert service.read("published")["revision"] == 1
    assert service.tasks.get(queued["id"])["status"] == "queued"
    assert len(service.tasks.list()) == 1


def test_offline_publication_validates_target_environment_without_exporting_it(
    deployment, monkeypatch
):
    root, service = deployment
    monkeypatch.delenv("SYNTHETIC_KEY", raising=False)
    target = service.read()["document"]
    target["providers"] = [{
        "id": "example", "protocol": "openai", "base_url": "https://example.test/v1",
        "api_key_env": "SYNTHETIC_KEY", "default_model": "example-model",
        "models": [{"model": "example-model"}],
    }]
    target["settings"]["quick_judge"].update(provider_id="example", model="example-model")
    prepared = service.prepare_deployment(target, 1)
    with stopped_service(root, "bot") as stopped:
        with pytest.raises(ConfigError, match="environment"):
            service.publish_offline(prepared["revision"], "invalid", stopped, environment={})
        result = service.publish_offline(
            prepared["revision"], "valid", stopped, environment={"SYNTHETIC_KEY": "sentinel"}
        )
    import os
    assert "SYNTHETIC_KEY" not in os.environ
    assert result["published_revision"] == prepared["revision"]


def test_offline_publication_reloads_profiles_after_asset_installation(deployment):
    root, service = deployment
    profiles = root / "config/client_profiles"
    profiles.mkdir()
    profile = profiles / "custom.toml"
    valid = 'format_version=1\nid="custom"\nlabel="Custom"\n[protocols.openai]\n'
    profile.write_text(valid)
    target = service.read()["document"]
    target["providers"] = [{
        "id": "example", "protocol": "openai", "base_url": "https://example.test/v1",
        "default_model": "example-model", "models": [{"model": "example-model"}],
        "client_fingerprint": "custom", "api_key_env": "SYNTHETIC_KEY",
    }]
    prepared = service.prepare_deployment(target, 1)
    profile.write_text("invalid TOML")
    with stopped_service(root, "bot") as stopped:
        with pytest.raises(ConfigError) as error:
            service.publish_offline(prepared["revision"], "profile-install", stopped)
        assert error.value.code == "invalid_profile"
        assert service.read("published")["revision"] == 1
        profile.write_text(valid)
        service.publish_offline(prepared["revision"], "profile-install", stopped)
    assert service.read("published")["revision"] == prepared["revision"]


def test_offline_publication_preserves_legacy_execution_snapshot_bytes(tmp_path):
    import time
    from quickquip.llm.config_document import empty_document
    from quickquip.llm.config_execution_store import ConfigExecutionStore
    from quickquip.llm.config_store import ConfigStore, dumps

    document = empty_document()
    document["format_version"] = 1
    path = tmp_path / "config/managed/config.db"
    ConfigStore(path).create(document)
    ConfigExecutionStore(tmp_path / "data/config_runtime.db").create(
        1, dumps(document), time.time()
    )
    service = ConfigService(path)
    with stopped_service(tmp_path, "bot") as stopped:
        service.publish_offline(1, "legacy-published", stopped)
    assert service.execution.read_published()["document"] == dumps(document)
    assert service.read("published")["document"]["format_version"] == 2
