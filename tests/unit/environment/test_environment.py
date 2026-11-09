"""Environment edits protect real file state, secret boundaries and request identity."""
import json

import pytest

from quickquip.environment.store import Store, EnvironmentError
from quickquip.common import runtime_environment as runtime
from quickquip.llm.config import ProviderConfig
from quickquip.llm.provider.openai import OpenAIProviderClient
from quickquip.llm.provider.base import LLMProviderError
from quickquip.llm.provider import LLMRequest
from tests.fixtures.client_fingerprints import protocol_only_config


@pytest.fixture
def store(tmp_path):
    (tmp_path / '.env').write_text('# retained\nEXAMPLE_API_KEY=old-key\nPORT=8080\n')
    return Store(tmp_path)


def save(store, changes, request_id='change1'):
    return store.execute('changes', {'expected_version': store.execute('list')['version'],
                                    'request_id': request_id, 'changes': changes})


def test_private_value_survives_quotes_and_dollars_without_public_echo(store):
    secret = 'sentinel\\path\'"${PORT}\n第二行#value'
    result = save(store, [{'name': 'NEW_API_KEY', 'action': 'create', 'value': secret}])
    assert store.execute('snapshot')['values']['NEW_API_KEY'] == secret
    assert '# retained' in store.path.read_text()
    for action, body in [('list', {}), ('operation', {'id': result['id']})]:
        assert secret not in json.dumps(store.execute(action, body), ensure_ascii=False)
        assert 'value' not in store.execute(action, body)
    assert (store.directory / 'active.json').exists() is False
    assert not (store.directory / 'candidate.env').exists()


def test_stale_edit_and_request_reuse_preserve_committed_value(store):
    body = {'expected_version': store.execute('list')['version'], 'request_id': 'same',
            'changes': [{'name': 'EXAMPLE_API_KEY', 'action': 'replace', 'value': 'new'}]}
    result = store.execute('changes', body)
    assert store.execute('changes', body)['version'] == result['version']
    with pytest.raises(EnvironmentError):
        store.execute('changes', {**body, 'request_id': 'another'})
    with pytest.raises(EnvironmentError):
        store.execute('changes', {**body, 'changes': [
            {'name': 'EXAMPLE_API_KEY', 'action': 'replace', 'value': 'different'}]})
    assert store.execute('snapshot')['values']['EXAMPLE_API_KEY'] == 'new'


def test_empty_and_delete_are_distinct_and_batch_failure_is_atomic(store):
    before = store.path.read_bytes()
    with pytest.raises(EnvironmentError):
        save(store, [{'name': 'EXAMPLE_API_KEY', 'action': 'empty'},
                     {'name': 'MISSING', 'action': 'replace', 'value': 'x'}])
    assert store.path.read_bytes() == before
    save(store, [{'name': 'EXAMPLE_API_KEY', 'action': 'empty'}])
    assert store.execute('snapshot')['values']['EXAMPLE_API_KEY'] == ''
    save(store, [{'name': 'EXAMPLE_API_KEY', 'action': 'delete'}], 'delete')
    assert 'EXAMPLE_API_KEY' not in store.execute('snapshot')['values']


def test_crash_after_file_replace_resumes_metadata_commit(store, monkeypatch):
    original = store._write
    def interrupt(name, value):
        if name == 'state.json' and (store.directory / 'active.json').exists():
            raise OSError('simulated power loss')
        return original(name, value)
    monkeypatch.setattr(store, '_write', interrupt)
    with pytest.raises(OSError):
        save(store, [{'name': 'EXAMPLE_API_KEY', 'action': 'replace', 'value': 'committed'}])
    recovered = Store(store.root)
    assert recovered.execute('snapshot')['values']['EXAMPLE_API_KEY'] == 'committed'
    assert recovered.execute('operation', {'id': 'change1'})['phase'] == 'saved'


def test_external_edit_during_recovery_is_not_overwritten(store, monkeypatch):
    original = store._replace
    monkeypatch.setattr(store, '_replace', lambda data: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        save(store, [{'name': 'EXAMPLE_API_KEY', 'action': 'replace', 'value': 'candidate'}])
    monkeypatch.setattr(store, '_replace', original)
    store.path.write_text('EXAMPLE_API_KEY=external\n')
    with pytest.raises(EnvironmentError):
        store.execute('snapshot')
    assert store.path.read_text() == 'EXAMPLE_API_KEY=external\n'


def config():
    return protocol_only_config(ProviderConfig(
        id='test', protocol='openai', base_url='https://example.test/v1',
        api_key_env='EXAMPLE_API_KEY', default_model='model', models=['model'],
        header_templates={'X-Test-Auth': 'Bearer ${EXAMPLE_API_KEY}'},
    ))


async def test_rotation_new_provider_and_deletion_reach_real_request_builder(store, monkeypatch):
    monkeypatch.setenv('EXAMPLE_API_KEY', 'stale-docker-key')
    monkeypatch.setattr(runtime, '_values', None)
    monkeypatch.setattr(runtime, '_version', None)
    import os
    baseline = dict(os.environ)
    first = store.execute('snapshot')
    runtime.install_snapshot(first, baseline)
    request = LLMRequest(
        model='model', system_prompt='', messages=[], max_output_tokens=1, temperature=0
    )
    with runtime.credential_scope():
        old = OpenAIProviderClient(config())
        save(store, [{'name': 'EXAMPLE_API_KEY', 'action': 'replace', 'value': 'rotated'}])
        new = store.execute('snapshot')
        runtime.install_snapshot(new, baseline)
        # Even a new client in the same logical task retains the pinned credential.
        retry = OpenAIProviderClient(config())
        _, old_headers, _ = await old._build_request_parts(request)
        _, retry_headers, _ = await retry._build_request_parts(request)
        assert old_headers['authorization'] == retry_headers['authorization']
        assert old_headers['authorization'] == 'Bearer stale-docker-key'
    _, headers, _ = await OpenAIProviderClient(config())._build_request_parts(request)
    assert headers['authorization'] == headers['X-Test-Auth'] == 'Bearer rotated'
    save(store, [{'name': 'NEW_API_KEY', 'action': 'create', 'value': 'initial'}], 'new')
    new = store.execute('snapshot')
    runtime.install_snapshot(new, baseline)
    from dataclasses import replace
    _, headers, _ = await OpenAIProviderClient(replace(
        config(), api_key_env='NEW_API_KEY', header_templates={}
    ))._build_request_parts(request)
    assert headers['authorization'] == 'Bearer initial'
    save(store, [{'name': 'EXAMPLE_API_KEY', 'action': 'delete'}], 'delete')
    new = store.execute('snapshot')
    runtime.install_snapshot(new, baseline)
    with pytest.raises(LLMProviderError):
        await OpenAIProviderClient(config())._build_request_parts(request)


def test_reading_credentials_during_verified_deployment_start_is_allowed(store):
    directory = store.root / 'data/config-sync'
    directory.mkdir(parents=True)
    (directory / 'maintenance.json').write_text(json.dumps(
        {'protocol': 2, 'token': 'deployment', 'allow_start': True}))
    assert store.execute('snapshot')['values']['EXAMPLE_API_KEY'] == 'old-key'
    from quickquip.common.config_writes import ConfigurationBusy
    with pytest.raises(ConfigurationBusy):
        save(store, [{'name': 'EXAMPLE_API_KEY', 'action': 'empty'}])


def test_native_restart_and_dependent_reference_keep_literals(store, monkeypatch):
    save(store, [{'name': 'LITERAL', 'action': 'create', 'value': '${PORT}'}])
    with store.path.open('a') as stream:
        stream.write('COPY=${LITERAL}\n')
    from quickquip.common.dotenv import load_dotenv
    monkeypatch.delenv('LITERAL', raising=False)
    monkeypatch.delenv('COPY', raising=False)
    load_dotenv(store.path)
    import os
    assert os.environ['LITERAL'] == os.environ['COPY'] == '${PORT}'
    assert store.execute('snapshot')['values']['COPY'] == '${PORT}'


def test_other_writers_cannot_overwrite_interrupted_environment_commit(store, monkeypatch):
    monkeypatch.setattr(store, '_replace', lambda data: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        save(store, [{'name': 'EXAMPLE_API_KEY', 'action': 'empty'}])
    from quickquip.common.config_writes import configuration_write, ConfigurationBusy
    with pytest.raises(ConfigurationBusy):
        with configuration_write(store.root / 'data'):
            pytest.fail('Other writers must not enter an interrupted environment transaction')


def test_startup_status_clears_after_new_boot_and_hides_comparison_proofs(store):
    import time
    current = store.execute('snapshot')
    startup = dict(current['values'])
    def ack(boot, values):
        store.execute('ack', {'role': 'web', 'boot_id': boot,
                             'version': store.execute('snapshot')['version'],
                             'names': sorted(values), 'updated_at': time.time(),
                             'startup_values': values})
    ack('before', startup)
    assert next(row for row in store.execute('list')['variables']
                if row['name'] == 'PORT')['states']['web'] == 'loaded'
    save(store, [{'name': 'PORT', 'action': 'replace', 'value': '9999'}])
    ack('before', startup)
    assert next(row for row in store.execute('list')['variables']
                if row['name'] == 'PORT')['states']['web'] == 'restart'
    ack('after', store.execute('snapshot')['values'])
    public = store.execute('list')
    assert next(row for row in public['variables']
                if row['name'] == 'PORT')['states']['web'] == 'loaded'
    assert '_startup' not in json.dumps(public)


def test_operation_reclassifies_a_new_key_after_provider_is_saved(store):
    import time
    from quickquip.llm.config_service import ConfigService
    before = store.execute('snapshot')
    result = save(store, [{'name': 'NEW_KEY', 'action': 'create', 'value': 'first'}])
    assert result['changes'][0]['mode'] == 'unknown'
    assert result['states']['NEW_KEY']['web'] == 'waiting'
    ack = {'role': 'web', 'boot_id': 'running', 'version': before['version'],
           'updated_at': time.time(), 'names': sorted(before['values']),
           'startup_values': before['values']}
    store.execute('ack', ack)
    assert store.execute('operation', {'id': result['id']})['states']['NEW_KEY']['web'] == 'loading'
    current = store.execute('snapshot')
    store.execute('ack', {**ack, 'version': current['version'],
                          'names': sorted(current['values'])})
    operation = store.execute('operation', {'id': result['id']})
    assert operation['states']['NEW_KEY']['web'] == 'synced'
    row = next(row for row in store.execute('list')['variables'] if row['name'] == 'NEW_KEY')
    assert row['mode'] == 'unknown'
    assert row['states']['web'] == 'synced'
    service = ConfigService(store.root / 'config/managed/config.db')
    service.initialize()
    draft = service.read()
    document = draft['document']
    document['providers'] = [{
        'id': 'new-provider', 'protocol': 'openai', 'base_url': 'https://example.test/v1',
        'api_key_env': 'NEW_KEY', 'default_model': 'test', 'models': [{'model': 'test'}],
    }]
    service.replace(document, draft['revision'])
    operation = store.execute('operation', {'id': result['id']})
    assert operation['changes'][0]['mode'] == 'credential'
    assert operation['states']['NEW_KEY']['web'] == 'loaded'
    row = next(row for row in store.execute('list')['variables'] if row['name'] == 'NEW_KEY')
    assert row['mode'] == 'credential'
    assert row['references'] == ['new-provider']
    save(store, [{'name': 'NEW_KEY', 'action': 'replace', 'value': 'second'}], 'later')
    assert store.execute('operation', {'id': result['id']})['phase'] == 'superseded'


def test_preview_distinguishes_known_startup_parameters_from_unclassified_names(store):
    names = (
        'NEW_PROVIDER_API_KEY', 'WEB_ADMIN_CUSTOM_API_KEY', 'WEB_ADMIN_PORT',
        'TIEBA_FORUM_KEYWORDS', 'QUICKQUIP_DEPLOY_LOCATION',
    )
    changes = [{'name': name, 'action': 'create',
                'value': 'local' if name == 'QUICKQUIP_DEPLOY_LOCATION' else 'example'}
               for name in names]
    preview = store.execute('preview', {'expected_version': store.execute('list')['version'],
                                        'changes': changes})
    modes = {row['name']: row['mode'] for row in preview['changes']}
    assert modes == {
        'NEW_PROVIDER_API_KEY': 'unknown', 'WEB_ADMIN_CUSTOM_API_KEY': 'unknown',
        'WEB_ADMIN_PORT': 'restart', 'TIEBA_FORUM_KEYWORDS': 'hot',
        'QUICKQUIP_DEPLOY_LOCATION': 'unknown',
    }


def test_metadata_is_read_as_utf8_in_a_non_utf8_native_process(store):
    import os
    import subprocess
    import sys
    program = (
        'from quickquip.environment.store import Store; '
        f's=Store({str(store.root)!r}); '
        "s.execute('changes', {'expected_version':s.execute('list')['version'], "
        "'request_id':'locale', 'changes':[{'name':'PORT','action':'replace','value':'9999'}]}); "
        "assert s.execute('operation', {'id':'locale'})['phase']=='saved'"
    )
    subprocess.run([sys.executable, '-c', program], check=True, env={
        **os.environ, 'PYTHONUTF8': '0', 'PYTHONCOERCECLOCALE': '0', 'LC_ALL': 'C',
        'PYTHONPATH': os.pathsep.join(map(str, sys.path)),
    })
