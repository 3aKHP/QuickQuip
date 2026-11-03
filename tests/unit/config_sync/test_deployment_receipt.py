"""Deployment decisions survive process failures and retain legacy ambiguity."""
import json

import pytest

from quickquip.config_sync.deployment_receipt import status


@pytest.mark.parametrize('committed,code,expected', [
    (True, '1', '0'), (True, None, '0'), (False, '1', '1'),
    (False, None, 'pending'), (None, '0', '0'), (None, '1', 'unknown'),
])
def test_commit_takes_precedence_over_exit_status(tmp_path, committed, code, expected):
    release = '20260907-020000-bbbbbbbbbbbb'
    target = tmp_path / 'releases' / release
    target.mkdir(parents=True)
    (target / '.complete').touch()
    (tmp_path / 'current').symlink_to(target)
    deploy = tmp_path / '.deploy'
    deploy.mkdir()
    if committed is not None:
        (deploy / f'{release}.transaction.json').write_text(json.dumps({'committed': committed}))
    if code is not None:
        (deploy / f'{release}.exit').write_text(code)
    assert status(tmp_path, release) == expected


def test_cleanup_waits_for_worker_exit(tmp_path):
    import subprocess
    from quickquip.config_sync.peers import Remote

    release = '20260907-020000-bbbbbbbbbbbb'
    incoming = tmp_path / '.deploy/incoming' / release
    incoming.mkdir(parents=True)
    (incoming / '.env').write_text('SYNTHETIC_KEY=example\n')
    peer = Remote.__new__(Remote)
    peer.root = str(tmp_path)

    def shell(command, body):
        return subprocess.check_output(['bash', '-c', command], text=True)

    peer._ssh = shell
    peer.cleanup_deployment(release)
    assert incoming.exists()
    (tmp_path / '.deploy' / f'{release}.exit').write_text('1')
    peer.cleanup_deployment(release)
    assert not incoming.exists()
