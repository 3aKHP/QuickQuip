"""Deployment preparation remains recoverable before a remote release is launched."""

import pytest

from quickquip.config_sync.deployment import prepare, finish
from quickquip.config_sync.peers import Local
from quickquip.config_sync.session import Session
from quickquip.configuration.activity import stopped_service
from quickquip.llm.config_service import ConfigService


@pytest.mark.parametrize("direction", ["push", "pull"])
def test_unlaunched_deployment_recovers_receiver_and_keeps_sender_changes(tmp_path, direction):
    roots = [tmp_path / name for name in ("local", "remote")]
    services = []
    for root in roots:
        root.mkdir()
        service = ConfigService(root / "config/managed/config.db")
        service.initialize()
        services.append(service)
        (root / ".env").write_text(
            "QUICKQUIP_DEPLOY_LOCATION=cloud\nQUICKQUIP_DEPLOY_RUNTIME=docker\n"
        )
    local, remote = services
    original_local = local.read()["document"]
    sender = local if direction == "push" else remote
    document = sender.read()["document"]
    document["settings"]["runtime"]["history_limit"] = 31
    saved = sender.prepare_deployment(document, 1)
    if direction == "pull":
        with stopped_service(roots[1], "bot") as stopped:
            sender.publish_offline(saved["revision"], "synthetic-web-apply", stopped)
    source_before = sender.read()
    session = Session(roots[0], remote_factory=lambda *_: Local(roots[1]))
    operation = prepare(session, direction)
    assert operation == session.pending()["id"]
    if direction == "pull":
        assert local.read()["document"] == document
        assert local.read("published")["document"] == original_local
    else:
        assert remote.read()["document"] == original_local
    assert finish(session)["phase"] == "recovered"
    assert sender.read() == source_before
    assert session.pending() is None
    if direction == "pull":
        assert local.read()["document"] == original_local
    for root in roots:
        assert not (root / "data/config-sync/maintenance.json").exists()
