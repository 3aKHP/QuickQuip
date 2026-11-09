"""Opt-in management must preserve legacy deployments and transferable deletions."""
from copy import deepcopy
from io import StringIO
import os
import subprocess
import sys

from dotenv import dotenv_values
from dotenv.main import DotEnv
import pytest

from quickquip.common.dotenv import load_dotenv, markers, read_environment
from quickquip.common import runtime_environment as runtime
from quickquip.configuration.inventory import body, entry
from quickquip.configuration import text
from quickquip.configuration.merge import reconcile
from quickquip.config_sync.reconciliation import plan
from quickquip.environment.store import Store, literal


@pytest.mark.parametrize('override', [True, False])
def test_unmarked_dotenv_matches_dependency_precedence_and_interpolation(tmp_path, monkeypatch,
                                                                       override):
    monkeypatch.setenv('EXTERNAL', 'external')
    monkeypatch.setenv('PARENT', 'injected-parent')
    content = (
        "PARENT=file-parent\nSINGLE='${PARENT}'\nDOUBLE=\"${PARENT}\"\n"
        'FROM_EXTERNAL=${EXTERNAL}\nDEFAULT=${ABSENT_FOR_COMPAT:-fallback}\n'
        'DUP=first\nDUP=${DUP}-last\nBARE\nEMPTY=\nBAD KEY=broken\n'
    )
    expected = DotEnv(None, stream=StringIO(content), override=override).dict()
    assert read_environment(content, override=override) == expected
    path = tmp_path / '.env'
    path.write_text(content, encoding='utf-8')
    expected_environment = dict(os.environ)
    for key, value in expected.items():
        if value is not None and (override or key not in expected_environment):
            expected_environment[key] = value
    # monkeypatch restores variables introduced by the real loader too.
    for key in expected:
        if key not in os.environ:
            monkeypatch.setenv(key, 'placeholder')
            monkeypatch.delenv(key)
    load_dotenv(path, override=override)
    assert dict(os.environ) == expected_environment
    assert 'BARE' not in os.environ


def test_literals_remain_exact_in_native_startup_and_tool_reading(tmp_path, monkeypatch):
    secret = 'a\\path\'"${PARENT}$$\n第二行#text'
    content = literal('SAVED', secret) + 'COPY=${SAVED}\nSINGLE=\'${EXTERNAL}\'\n'
    monkeypatch.setenv('EXTERNAL', 'legacy-reference')
    monkeypatch.delenv('SAVED', raising=False)
    monkeypatch.delenv('COPY', raising=False)
    monkeypatch.delenv('SINGLE', raising=False)
    path = tmp_path / '.env'
    path.write_text(content, encoding='utf-8')
    values = read_environment(content)
    assert values['SAVED'] == values['COPY'] == secret
    assert values['SINGLE'] == 'legacy-reference'
    load_dotenv(path)
    assert os.environ['SAVED'] == os.environ['COPY'] == secret
    assert path.read_text(encoding='utf-8') == content
    # Outside marked bindings, tooling retains dotenv_values file precedence.
    monkeypatch.setenv('EXTERNAL', 'injected')
    unmarked = 'EXTERNAL=file\nCOPY=${EXTERNAL}\nBARE\n'
    assert read_environment(unmarked) == dotenv_values(stream=StringIO(unmarked))


def test_disabled_bootstrap_and_transport_have_no_management_side_effects(tmp_path):
    (tmp_path / '.env').write_text("KEY=file\nCOPY='${KEY}'\n", encoding='utf-8')
    program = '''
import os, threading
from pathlib import Path
from quickquip.common import env
env.PROJECT_ROOT = Path(ROOT)
env._ROOT_ENV_LOADED = False
os.environ.pop('COPY', None)
from quickquip.environment import bootstrap, transport
from quickquip.environment.store import EnvironmentError
from quickquip.common import runtime_environment
root = Path(ROOT)
env.PROJECT_ROOT = root
os.environ['KEY'] = 'injected'
# A configured socket and an existing .env must not opt in.
os.environ['QUICKQUIP_ENV_SOCKET'] = '/missing/environment.sock'
bootstrap.start('web')
assert os.environ['COPY'] == 'injected'
assert not runtime_environment.managed()
assert not any(t.name == 'environment-refresh' for t in threading.enumerate())
try: transport.call('list')
except EnvironmentError as error: assert str(error) == 'environment_management_disabled'
else: raise AssertionError('disabled transport accepted a request')
assert not (root / 'data').exists()
os.environ['QUICKQUIP_ENV_MANAGEMENT_ENABLED'] = 'true'
assert not env.environment_management_enabled(), 'switch must be frozen until restart'
'''
    subprocess.run([sys.executable, '-c', 'ROOT=' + repr(str(tmp_path)) + '\n' + program],
                   check=True, env={**os.environ, 'QUICKQUIP_ENV_MANAGEMENT_ENABLED': 'false',
                                    'PYTHONPATH': os.pathsep.join(map(str, sys.path))})


def test_runtime_overlays_only_managed_values_and_explicit_deletions(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, '_values', None)
    monkeypatch.setattr(runtime, '_version', None)
    baseline = {'INJECTED_ONLY': 'external', 'KEY': 'stale', 'MANUAL': 'external-wins',
                'EMPTY': 'old', 'REMOVED': 'old'}
    content = ('KEY=file\nMANUAL=file\n' + literal('EMPTY', '')
               + '# quickquip:deleted REMOVED\n')
    (tmp_path / '.env').write_text(content, encoding='utf-8')
    store = Store(tmp_path)
    initial = runtime.install_snapshot(store.execute('snapshot'), baseline)
    assert initial == {'INJECTED_ONLY': 'external', 'KEY': 'stale',
                       'MANUAL': 'external-wins', 'EMPTY': ''}
    with runtime.credential_scope():
        current = store.execute('list')
        store.execute('changes', {'request_id': 'rotate', 'expected_version': current['version'],
                                 'changes': [{'name': 'KEY', 'action': 'replace', 'value': 'new'},
                                             {'name': 'NEW', 'action': 'create',
                                              'value': 'first'}]})
        runtime.install_snapshot(store.execute('snapshot'), baseline)
        assert runtime.get('KEY') == 'stale'
        assert runtime.get('NEW') is None
    assert runtime.get('KEY') == 'new'
    assert runtime.get('NEW') == 'first'
    assert runtime.get('INJECTED_ONLY') == 'external'


def test_delete_is_portable_deduplicated_and_can_be_recreated(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, '_values', None)
    monkeypatch.setattr(runtime, '_version', None)
    (tmp_path / '.env').write_text('KEY=one\nKEY=two\nOTHER=keep\n', encoding='utf-8')
    store = Store(tmp_path)
    store.execute('changes', {'request_id': 'delete',
                             'expected_version': store.execute('list')['version'],
                             'changes': [{'name': 'KEY', 'action': 'delete'}]})
    assert store.path.read_text(encoding='utf-8') == '# quickquip:deleted KEY\nOTHER=keep\n'
    transferred = tmp_path / 'receiver'
    transferred.mkdir()
    (transferred / '.env').write_bytes(store.path.read_bytes())
    result = Store(transferred).execute('snapshot')
    assert 'KEY' not in runtime.install_snapshot(result, {'KEY': 'injected'})
    # Disabled startup continues to use the old external fallback.
    monkeypatch.setenv('KEY', 'injected')
    load_dotenv(transferred / '.env')
    assert os.environ['KEY'] == 'injected'
    store.execute('changes', {'request_id': 'recreate',
                             'expected_version': store.execute('list')['version'],
                             'changes': [{'name': 'KEY', 'action': 'create', 'value': ''}]})
    assert markers(store.path.read_text(encoding='utf-8')) == ({'KEY'}, set())
    assert runtime.install_snapshot(store.execute('snapshot'), {'KEY': 'injected'})['KEY'] == ''


def test_history_adoption_is_transactional_and_ignores_restored_definitions(tmp_path, monkeypatch):
    (tmp_path / '.env').write_bytes(b'RESTORED=manual\n# retained\n')
    store = Store(tmp_path)
    store.execute('list')
    operations = {
        'old': {'saved_at': 1, 'changes': [{'name': 'GONE', 'action': 'delete'},
                                         {'name': 'RESTORED', 'action': 'delete'},
                                         {'name': 'LATER', 'action': 'delete'}]},
        'new': {'saved_at': 2, 'changes': [{'name': 'LATER', 'action': 'create'}]},
    }
    store._write('operations.json', operations)
    original = store._write
    def interrupt(name, value):
        if name == 'state.json' and (store.directory / 'active.json').exists():
            raise OSError('simulated crash')
        return original(name, value)
    monkeypatch.setattr(store, '_write', interrupt)
    with pytest.raises(OSError):
        store.execute('initialize')
    recovered = Store(tmp_path)
    recovered.execute('initialize')
    assert recovered.path.read_bytes() == b'RESTORED=manual\n# retained\n# quickquip:deleted GONE\n'
    assert recovered._json('operations.json', {}) == operations
    assert not (store.directory / 'active.json').exists()
    assert recovered.execute('snapshot')['deleted'] == ['GONE']


def test_workspace_and_sync_merge_literal_flags_and_deletions_without_rewriting_other_lines():
    original = b'# retained\nKEY=old\nOTHER=original\n'
    source = ('# retained\n# quickquip:deleted KEY\nOTHER=original\n'
              + literal('NEW', '${PORT}')).encode()
    receiver = b'# retained\nKEY=old\nOTHER=receiver\n'
    expected = {'KEY': ['old'], 'OTHER': ['original']}
    assert text.parse('.env', original) == expected
    conflicts = []
    merged = reconcile(text.parse('.env', original), text.parse('.env', source),
                       text.parse('.env', receiver), conflicts=conflicts)
    assert not conflicts
    rendered = text.render('.env', merged, receiver)
    assert b'# retained\n' in rendered
    assert read_environment(rendered.decode()) == {'OTHER': 'receiver', 'NEW': '${PORT}'}
    assert markers(rendered.decode()) == ({'NEW'}, {'KEY'})
    base = {'document': {}, 'scopes': {}, 'text_modes': {},
            'files': {'.env': entry(original)}}
    left, right = deepcopy(base), deepcopy(base)
    left['files']['.env'], right['files']['.env'] = entry(source), entry(receiver)
    synced = plan(base, left, right)
    assert not synced['conflicts']
    assert text.parse('.env', body(synced['target']['files']['.env'])) == merged
    # Re-creating an unmarked value removes the literal flag and tombstone too.
    plain = text.render('.env', {'KEY': ['restored'], 'OTHER': ['receiver'],
                                'NEW': ['${PORT}']}, rendered)
    assert markers(plain.decode()) == (set(), set())


def test_marker_text_in_a_multiline_secret_is_not_a_deletion():
    content = "SECRET='line\n# quickquip:deleted INJECTED\nlast'\n"
    assert markers(content) == (set(), set())
    assert text.parse('.env', content.encode()) == {
        'SECRET': ['line\n# quickquip:deleted INJECTED\nlast']}


def test_native_enabled_bootstrap_rotates_credentials_and_restart_keeps_deletion(tmp_path):
    (tmp_path / '.env').write_text(
        'QUICKQUIP_ENV_MANAGEMENT_ENABLED=true\nKEY=file\n', encoding='utf-8')
    program = '''
import os, threading
from pathlib import Path
from quickquip.common import env
env.PROJECT_ROOT = Path(ROOT); env._ROOT_ENV_LOADED = False
os.environ.pop('QUICKQUIP_ENV_SOCKET', None)
os.environ.pop('QUICKQUIP_ENV_WRITE_SOCKET', None)
os.environ.pop('QUICKQUIP_MANAGED_CONTAINER', None)
from quickquip.environment import bootstrap
from quickquip.environment.store import Store
from quickquip.common import runtime_environment as runtime
os.environ['KEY'] = 'injected'
os.environ['INJECTED_ONLY'] = 'preserved'
bootstrap.start('web')
assert runtime.get('INJECTED_ONLY') == 'preserved'
store = Store(ROOT)
if MODE == 'restart':
    assert runtime.get('KEY') is None
else:
    assert runtime.get('KEY') == 'injected'
    acknowledged = threading.Event()
    real_call = bootstrap.call
    desired = None
    def observed(action, body=None):
        result = real_call(action, body)
        if action == 'ack' and body['version'] == desired:
            acknowledged.set()
        return result
    bootstrap.call = observed
    with runtime.credential_scope():
        saved = store.execute('changes', {
            'request_id': 'rotate', 'expected_version': store.execute('list')['version'],
            'changes': [{'name': 'KEY', 'action': 'replace', 'value': 'rotated'}]})
        desired = saved['version']
        assert acknowledged.wait(10), 'poller did not acknowledge the saved version'
        assert runtime.get('KEY') == 'injected'
    assert runtime.get('KEY') == 'rotated'
    store.execute('changes', {
        'request_id': 'delete', 'expected_version': store.execute('list')['version'],
        'changes': [{'name': 'KEY', 'action': 'delete'}]})
'''
    for mode in ('rotation', 'restart'):
        subprocess.run([sys.executable, '-c', 'ROOT=' + repr(str(tmp_path))
                        + '\nMODE=' + repr(mode) + '\n' + program], check=True, timeout=20,
                       env={**os.environ, 'QUICKQUIP_ENV_MANAGEMENT_ENABLED': 'true',
                            'PYTHONPATH': os.pathsep.join(map(str, sys.path))})
