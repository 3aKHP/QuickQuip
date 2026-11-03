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


def test_pull_interrupted_before_local_prepare_releases_client_state(tmp_path, monkeypatch):
    from quickquip.configuration.errors import ConfigError

    roots = [tmp_path / name for name in ("local", "remote")]
    for root in roots:
        root.mkdir()
        ConfigService(root / "config/managed/config.db").initialize()
        (root / ".env").write_text(
            "QUICKQUIP_DEPLOY_LOCATION=cloud\nQUICKQUIP_DEPLOY_RUNTIME=docker\n"
        )
    original = Local.call

    def disconnect(self, action, body=None):
        if self.root == roots[0] and action == "prepare":
            raise ConfigError("transport_error", "lost local preparation")
        return original(self, action, body)

    monkeypatch.setattr(Local, "call", disconnect)
    session = Session(roots[0], remote_factory=lambda *_: Local(roots[1]))
    with pytest.raises(ConfigError, match="lost local"):
        prepare(session, "pull")
    assert finish(session)["phase"] == "recovered"
    assert session.pending() is None


@pytest.mark.parametrize("helper_mode", ["current", "recorded"])
def test_confirmed_deployment_resumes_after_new_configuration_edit(
    tmp_path, monkeypatch, helper_mode
):
    from quickquip.config_sync.installation import Installation
    from quickquip.llm.scope_settings import ScopeSettingsRepository

    class RemotePeer(Local):
        def deployment_status(self, release):
            raise AssertionError('Confirmed configuration already carries the receipt')

    roots = [tmp_path / name for name in ('local', 'remote')]
    for root in roots:
        root.mkdir()
        ConfigService(root / 'config/managed/config.db').initialize()
        (root / '.env').write_text(
            'QUICKQUIP_DEPLOY_LOCATION=cloud\nQUICKQUIP_DEPLOY_RUNTIME=docker\n'
        )
    remote = RemotePeer(roots[1])
    session = Session(roots[0], remote_factory=lambda *_: remote)
    operation = prepare(session, 'push')
    receiver = Installation(roots[1])
    with receiver.owned(operation) as record:
        record['deployment'] = '20260907-020000-bbbbbbbbbbbb'
        receiver.save(record)
    receiver.install(operation)
    receiver.verify(operation)
    receiver.confirm(operation)
    repository = ScopeSettingsRepository(roots[1] / 'config/managed/config.db')
    repository.update_group_settings('10001', history_limit=9)
    import json
    import subprocess
    from quickquip.config_sync.compose import Compose
    from quickquip.configuration.errors import ConfigError
    from quickquip.config_sync.worker import execute

    (roots[1] / 'docker-compose.yml').write_text('services: {}\n')
    remote.runtime = 'docker'
    remote.controller = Compose(roots[1])
    remote.controller.helper_image = 'sha256:current' if helper_mode == 'current' else None
    pending = session.pending()
    pending['remote_original']['helper_image'] = (
        'sha256:deleted' if helper_mode == 'current' else 'sha256:recorded'
    )
    session.state.write('qqsync/client.json', pending)
    helper_calls = []

    def docker(command, environment, cwd, payload):
        if command[:2] == ['docker', 'compose']:
            raise ConfigError('compose_failed', 'Interrupted environment prevents discovery')
        assert 'sha256:deleted' not in command, 'Old helper was garbage collected'
        assert 'sha256:' + helper_mode in command
        helper_calls.append(command[-3])
        return json.dumps(execute(roots[1], command[-3], payload))

    remote.controller.runner = docker
    monkeypatch.setattr(remote, 'call', lambda action, body=None:
                        remote.controller.call(action, body or {}))
    cleanups = []

    def cleanup(release):
        cleanups.append(release)
        if len(cleanups) == 1:
            raise subprocess.TimeoutExpired('ssh', 1)

    monkeypatch.setattr(remote, 'cleanup_deployment', cleanup, raising=False)
    assert finish(session)['phase'] == 'confirmed'
    assert repository.get_group_settings('10001').history_limit == 9
    assert session.pending() is None
    baseline = session.state.read('qqsync/peers.json')
    assert finish(session)['phase'] == 'confirmed'
    assert session.state.read('qqsync/peers.json') == baseline
    assert len(cleanups) == 2
    assert helper_calls == ['inspect', 'confirm', 'inspect']


def test_completed_cleanup_keeps_commit_when_remote_is_offline(tmp_path, monkeypatch, caplog):
    from quickquip.configuration.errors import ConfigError

    session = Session(tmp_path)
    record = {
        'id': 'a' * 32, 'phase': 'confirmed', 'deployment': True, 'direction': 'push',
        'route': {'location': 'cloud', 'runtime': 'docker',
                  'host': 'synthetic', 'remote_dir': '/srv/synthetic'},
    }
    session.state.write('qqsync/client.json', record)

    def offline(mode):
        raise ConfigError('transport_error', 'Remote unavailable')

    monkeypatch.setattr(session, '_peers', offline)
    assert finish(session) == {'phase': 'confirmed', 'direction': 'push'}
    assert session.state.read('qqsync/client.json') == record
    assert 'transport_error' in caplog.text
