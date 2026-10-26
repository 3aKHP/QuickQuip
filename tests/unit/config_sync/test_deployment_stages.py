"""Release staging stays private; stopped publication precedes the first new startup."""

from copy import deepcopy
import os
import uuid

import pytest

from quickquip.config_sync.capture import read
from quickquip.config_sync.deployment_worker import execute
from quickquip.config_sync.installation import Installation
from quickquip.configuration.inventory import entry
from quickquip.llm.config_service import ConfigService


@pytest.mark.skipif(os.name == "nt", reason="Linux release-layout deployment")
def test_candidate_assets_and_env_stage_before_offline_publication_and_restore(tmp_path):
    previous = "20261025-000000-111111111111"
    release = "20261026-000000-222222222222"
    old, new = [tmp_path / "releases" / name for name in (previous, release)]
    old.mkdir(parents=True)
    new.mkdir()
    (tmp_path / "current").symlink_to(old, target_is_directory=True)
    (tmp_path / ".env").write_text(
        "QUICKQUIP_DEPLOY_LOCATION=cloud\nQUICKQUIP_DEPLOY_RUNTIME=docker\nPORT=5000\n"
    )
    service = ConfigService(
        tmp_path / "config/managed/config.db", config_dir=old / "config", data_dir=tmp_path / "data"
    )
    service.initialize()
    (old / "config").mkdir()
    (old / "config/admins.toml").write_text("global_admins=[]\n")
    receiver = Installation(tmp_path)
    before = read(receiver.layout, "published")
    target = deepcopy(before["snapshot"])
    target["document"]["settings"]["runtime"]["history_limit"] = 29
    target["files"][".env"] = entry((tmp_path / ".env").read_bytes().replace(b"5000", b"5001"))
    target["files"].pop("config/admins.toml")
    operation = uuid.uuid4().hex
    receiver.prepare(operation, before, target, publish=True)
    execute(tmp_path, previous, "bind-deployment", operation, release)
    staged_env = tmp_path / ".deploy/incoming" / release / "shared/.env"
    assert b"PORT=5001" in staged_env.read_bytes()
    execute(tmp_path, previous, "stage", operation, release)
    assert (old / "config/admins.toml").exists()
    assert not (new / "config/admins.toml").exists()
    assert "PORT=5000" in (tmp_path / ".env").read_text()
    assert service.read("published")["document"] == before["published"]
    # deploy-v4's shared apply and stopped installation happen before changing current.
    (tmp_path / ".env").write_bytes(staged_env.read_bytes())
    (tmp_path / ".env").chmod(staged_env.stat().st_mode & 0o777)
    execute(tmp_path, release, "candidate-commit", operation)
    assert service.read("published")["document"] == target["document"]
    assert (tmp_path / "current").resolve() == old
    execute(tmp_path, previous, "recover", operation)
    receiver.recovered(operation)
    assert read(receiver.layout, "published")["snapshot"] == before["snapshot"]
