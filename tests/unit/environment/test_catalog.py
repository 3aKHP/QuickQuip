"""Fixed catalog, definition states and template evidence stay accurate and private."""
import json

import pytest

from quickquip.environment.catalog import CATALOG, fixed_usages
from quickquip.environment.store import Store, HOT, STARTUP


def directory(store):
    return store.execute('list', {'include_directory': True})['directory']


def row(rows, name):
    return next(item for item in rows if item['name'] == name)


def test_hot_and_startup_names_are_fully_catalogued():
    names = set(HOT) | set(STARTUP)
    missing = names - set(CATALOG)
    assert not missing, missing
    for name in HOT:
        assert CATALOG[name]['groups'] == ['runtime.tieba']
        actions = {relation['action'] for relation in CATALOG[name]['relations']}
        assert actions == {'next_tieba_task'}
    for name in ('QUICKQUIP_DEPLOY_LOCATION', 'QUICKQUIP_DEPLOY_RUNTIME',
                 'QUICKQUIP_DEPLOY_SSH_HOST', 'QUICKQUIP_DEPLOY_REMOTE_DIR'):
        assert CATALOG[name]['groups'] == ['deployment.connection']
        assert all(relation['action'] == 'next_deployment'
                   for relation in CATALOG[name]['relations'])
    for name in ('PIP_INDEX_URL', 'PIP_TRUSTED_HOST', 'PLAYWRIGHT_BASE_IMAGE'):
        assert CATALOG[name]['groups'] == ['deployment.image']
        assert all(relation['action'] == 'rebuild_image'
                   for relation in CATALOG[name]['relations'])
    assert CATALOG['QUICKQUIP_SEARXNG_BASE_URL']['groups'] == ['services.native.search']
    assert CATALOG['SEARXNG_BASE_URL']['groups'] == ['services.native.search']


def test_onebot_aliases_map_to_canonical_fields():
    for alias, canonical in (
        ('ONEBOT_V11_ACCESS_TOKEN', 'ONEBOT_ACCESS_TOKEN'),
        ('ONEBOT_V11_SECRET', 'ONEBOT_SECRET'),
        ('ONEBOT_V11_WS_URLS', 'ONEBOT_WS_URLS'),
        ('ONEBOT_V11_API_ROOTS', 'ONEBOT_API_ROOTS'),
    ):
        assert CATALOG[alias]['alias_of'] == canonical


def test_framework_fields_match_installed_nonebot_and_onebot():
    from nonebot.adapters.onebot.v11.config import Config as OneBotConfig
    from nonebot.config import Config, Env

    nonebot_fields = set(Config.model_fields) | set(Env.model_fields)
    onebot_fields = set(OneBotConfig.model_fields)
    for name in ('ENVIRONMENT', 'LOG_LEVEL', 'API_TIMEOUT', 'SUPERUSERS', 'NICKNAME',
                 'COMMAND_START', 'COMMAND_SEP', 'SESSION_EXPIRE_TIMEOUT',
                 'DRIVER', 'HOST', 'PORT'):
        assert name.lower() in nonebot_fields, name
    for name in ('ONEBOT_ACCESS_TOKEN', 'ONEBOT_WS_URLS', 'ONEBOT_SECRET',
                 'ONEBOT_API_ROOTS'):
        assert name.lower() in onebot_fields, name


def test_definition_states_and_actions_matrix(tmp_path):
    (tmp_path / '.env').write_text(
        'MANAGED_KEY=managed-secret # quickquip:literal\n'
        'BARE_KEY\n'
        'EMPTY_KEY=\n'
        'FULL_KEY=value\n'
        '# quickquip:deleted DELETED_KEY\n'
        'CONFLICT_KEY=kept\n'
        '# quickquip:deleted CONFLICT_KEY\n')
    clean = tmp_path / 'clean'
    clean.mkdir()
    (clean / '.env').write_text('# quickquip:deleted DELETED_KEY\n')
    rows = directory(Store(tmp_path))
    by_name = {item['name']: item for item in rows}

    assert by_name['FULL_KEY']['definition'] == {
        'present': True, 'value_state': 'nonempty',
        'managed_literal': False, 'deletion_marker': False}
    assert by_name['FULL_KEY']['allowed_actions'] == ['replace', 'empty', 'delete']
    assert by_name['MANAGED_KEY']['definition']['managed_literal'] is True
    assert by_name['BARE_KEY']['definition']['value_state'] == 'bare'
    assert by_name['EMPTY_KEY']['definition']['value_state'] == 'empty'
    assert by_name['BARE_KEY']['allowed_actions'] == ['replace', 'empty', 'delete']
    assert by_name['DELETED_KEY']['definition'] == {
        'present': False, 'value_state': 'missing',
        'managed_literal': False, 'deletion_marker': True}
    assert by_name['DELETED_KEY']['allowed_actions'] == ['create']
    conflict = by_name['CONFLICT_KEY']['definition']
    assert conflict['present'] is True and conflict['deletion_marker'] is True
    assert conflict['conflict'] is True and conflict['value_state'] == 'nonempty'
    assert by_name['CONFLICT_KEY']['allowed_actions'] == ['create']

    store = Store(clean)
    store.execute('changes', {
        'expected_version': store.execute('list')['version'], 'request_id': 'recreate',
        'changes': [{'name': 'DELETED_KEY', 'action': 'create', 'value': 'revived'}]})
    assert 'DELETED_KEY="revived"' in store.path.read_text()
    with pytest.raises(Exception):
        Store(tmp_path).execute('changes', {
            'expected_version': Store(tmp_path).execute('list')['version'],
            'request_id': 'conflict',
            'changes': [{'name': 'FULL_KEY', 'action': 'replace', 'value': 'blocked'}]})


def test_undefined_fixed_items_stay_out_of_legacy_variables(tmp_path):
    (tmp_path / '.env').write_text('EXISTING=value\n')
    store = Store(tmp_path)
    legacy = store.execute('list')
    assert {row['name'] for row in legacy['variables']} == {'EXISTING'}
    assert legacy['suggestions'] == []
    rows = directory(store)
    by_name = {item['name']: item for item in rows}
    assert 'PIP_INDEX_URL' in by_name
    assert by_name['PIP_INDEX_URL']['definition']['present'] is False
    assert by_name['PIP_INDEX_URL']['allowed_actions'] == ['create']
    assert by_name['PYTHONPATH']['evidence_flags'].get('internal') is True
    assert by_name['PYTHONPATH']['allowed_actions'] == []
    assert by_name['QUICK_LOGIN_QQ']['allowed_actions'] == []


def test_defined_internal_variables_keep_the_edit_contract(tmp_path):
    (tmp_path / '.env').write_text('PYTHONPATH=/custom\n')
    rows = directory(Store(tmp_path))
    pythonpath = row(rows, 'PYTHONPATH')
    assert pythonpath['definition']['present'] is True
    assert pythonpath['allowed_actions'] == ['replace', 'empty', 'delete']
    store = Store(tmp_path)
    store.execute('changes', {
        'expected_version': store.execute('list')['version'], 'request_id': 'internal',
        'changes': [{'name': 'PYTHONPATH', 'action': 'replace', 'value': '/other'}]})
    assert 'PYTHONPATH="/other"' in store.path.read_text()


def test_example_only_entries_are_flagged_and_cleared_by_real_references(tmp_path):
    referenced = tmp_path / 'referenced'
    referenced.mkdir()
    (referenced / '.env').write_text('EXISTING=value\n')
    (referenced / '.env.example').write_text('EXISTING=value\nUNKNOWN_EXAMPLE_KEY=\n')
    from quickquip.llm.config_service import ConfigService
    service = ConfigService(referenced / 'config/managed/config.db')
    service.initialize()
    draft = service.read()
    draft['document']['providers'] = [{
        'id': 'example-provider', 'protocol': 'openai',
        'base_url': 'https://example.test/v1', 'api_key_env': 'UNKNOWN_EXAMPLE_KEY',
        'default_model': 'model', 'models': [{'model': 'model'}],
    }]
    service.replace(draft['document'], draft['revision'])
    store = Store(referenced)
    rows = directory(store)
    example_key = row(rows, 'UNKNOWN_EXAMPLE_KEY')
    assert 'example_only' not in example_key['evidence_flags']
    assert example_key['allowed_actions'] == ['create']
    assert store.execute('list')['suggestions'] == ['UNKNOWN_EXAMPLE_KEY']

    unreferenced = tmp_path / 'unreferenced'
    unreferenced.mkdir()
    (unreferenced / '.env').write_text('EXISTING=value\n')
    (unreferenced / '.env.example').write_text('EXISTING=value\nUNKNOWN_EXAMPLE_KEY=\n')
    rows = directory(Store(unreferenced))
    example_key = row(rows, 'UNKNOWN_EXAMPLE_KEY')
    assert example_key['evidence_flags'].get('example_only') is True
    assert example_key['allowed_actions'] == ['create']


def test_template_evidence_and_secrets(tmp_path):
    (tmp_path / '.env').write_text('QQ_ACCOUNT=1000000000\n')
    (tmp_path / 'prod.example').mkdir()
    (tmp_path / 'prod.example/docker-compose.yml').write_text(
        'services:\n'
        '  quickquip:\n'
        '    build:\n'
        '      args:\n'
        '        PIP_INDEX_URL: "${PIP_INDEX_URL:-https://mirror.example/simple}"\n'
        '    environment:\n'
        '      HOST: "0.0.0.0"\n'
        '      SEARXNG_BASE_URL: "${QUICKQUIP_SEARXNG_BASE_URL:?set it}"\n')
    (tmp_path / 'docker').mkdir()
    (tmp_path / 'docker/Dockerfile.prod').write_text(
        'ARG PLAYWRIGHT_BASE_IMAGE=playwright:fixed\n')
    usages, errors = fixed_usages(tmp_path)
    assert errors == []
    payload = json.dumps(usages)
    assert 'mirror.example' not in payload
    assert 'playwright:fixed' not in payload
    assert 'set it' not in payload

    rows = directory(Store(tmp_path))
    qq = row(rows, 'QQ_ACCOUNT')
    mapping = [relation for relation in qq['relations']
               if relation['target_name'] == 'QUICK_LOGIN_QQ']
    assert mapping and mapping[0]['required'] is True
    searxng_map = row(rows, 'QUICKQUIP_SEARXNG_BASE_URL')
    assert any(relation['required'] for relation in searxng_map['relations'])
    host = row(rows, 'HOST')
    assert any(relation['required_action'] == 'edit_compose_then_recreate'
               and relation['delivery'] == 'container_env_fixed'
               for relation in host['relations'])
    pip = row(rows, 'PIP_INDEX_URL')
    assert pip['definition']['present'] is False
    build_relations = [relation for relation in pip['relations']
                       if relation['delivery'] == 'build_arg']
    assert build_relations and all(
        relation['required_action'] == 'rebuild_image' for relation in build_relations)
    playwright = row(rows, 'PLAYWRIGHT_BASE_IMAGE')
    assert any(relation.get('object_id') == 'quickquip-app'
               for relation in playwright['relations'])


def test_real_prod_directory_and_overrides_are_never_read(tmp_path):
    (tmp_path / '.env').write_text('EXISTING=value\n')
    prod = tmp_path / 'prod'
    prod.mkdir()
    (prod / 'docker-compose.yml').write_text('services: {x: {environment: [SENTINEL]}}')
    usages, errors = fixed_usages(tmp_path)
    assert errors == []
    assert 'SENTINEL' not in json.dumps(usages)
    rows = directory(Store(tmp_path))
    assert 'SENTINEL' not in json.dumps(rows)


def test_invalid_packaged_template_is_sanitized(tmp_path):
    (tmp_path / '.env').write_text('EXISTING=value\n')
    (tmp_path / 'prod.example').mkdir()
    (tmp_path / 'prod.example/docker-compose.yml').write_text(
        'services: [private-sentinel-broken')
    rows = directory(Store(tmp_path))
    result = Store(tmp_path).execute('list', {'include_directory': True})
    assert {'component': 'compose_template',
            'code': 'directory_source_unavailable'} in result['directory_errors']
    assert 'private-sentinel-broken' not in json.dumps(rows)
    assert row(rows, 'TZ')['definition']['present'] is False


def test_search_and_trace_groups(tmp_path):
    (tmp_path / '.env').write_text('EXISTING=value\n')
    rows = directory(Store(tmp_path))
    assert row(rows, 'SEARXNG_SAFE_SEARCH')['groups'] == ['services.native.search']
    assert row(rows, 'LLM_TRACE_FLAG_FILE')['groups'] == ['runtime.trace']
    trace = row(rows, 'LLM_TRACE_FLAG_FILE')
    assert trace['definition']['present'] is False
    assert trace['states'] == {}
    assert trace['allowed_actions'] == ['create']


def test_catalog_suggest_and_defaults_surface_on_entries(tmp_path):
    (tmp_path / '.env').write_text('QQ_ACCOUNT=1000000000\n')
    rows = directory(Store(tmp_path))
    assert row(rows, 'QQ_ACCOUNT').get('suggest') is True
    assert 'suggest' not in row(rows, 'TZ')
    token = row(rows, 'ONEBOT_ACCESS_TOKEN')
    assert token['default_present'] is True
    assert token['default_origin'] == 'compose_template'
    assert row(rows, 'QUICKQUIP_ROOT')['default_present'] is True
    assert row(rows, 'SEARXNG_PUBLIC_BASE_URL')['default_present'] is True
    assert 'default_present' not in row(rows, 'WEB_ADMIN_PASSWORD')
