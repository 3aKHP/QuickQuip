"""Read-only consumer projection keeps relationships rich and values private."""
import json

from quickquip.environment.consumption import build_directory


GENERATION = '''
[generation.image]
enabled = true
[[generation.image.providers]]
id = "minimax-image"
protocol = "minimax_images"
api_key_env = "MINIMAX_API_KEY"
[[generation.image.providers]]
id = "computed"
protocol = "minimax_images"
api_key_env = "${KEY_SELECTOR}"

[generation.audio]
enabled = true
[[generation.audio.providers]]
id = "minimax-audio"
protocol = "minimax_t2a_http"
api_key_env = "MINIMAX_API_KEY"
[[generation.audio.providers]]
id = "local-tts"
protocol = "openai_tts"
api_key_env = "LOCAL_TTS_KEY"
[[generation.audio.providers]]
id = "header-tts"
protocol = "minimax_t2a_http"
api_key_env = "AUDIO_KEY"
headers = { X-Key = "${GENERATION_HEADER_KEY}" }

[generation.music]
enabled = true
[[generation.music.providers]]
id = "minimax-music"
protocol = "minimax_music"
api_key_env = "MINIMAX_API_KEY"

[generation.asr]
enabled = true
[[generation.asr.providers]]
id = "zhipu-asr"
protocol = "openai_transcriptions"
api_key_env = "ZHIPU_API_KEY"

[generation.svg]
enabled = "${SVG_SWITCH:-true}"
'''


def provider(name, key, enabled=True):
    return {
        'id': name, 'protocol': 'openai', 'base_url': 'https://example.test/v1',
        'api_key_env': key, 'default_model': 'm', 'enabled': enabled,
        'headers': {'Authorization': f'Bearer ${{{key}}}', 'X-Secret': 'private-sentinel'},
        'parameters': {'extra_body': {
            'credential': '${PROVIDER_PARAM:-fallback-secret}',
            'api_key_env': 'LITERAL_BODY_VALUE',
        }},
        'models': [{'model': 'm', 'parameters': {'credential': '${MODEL_KEY}'}}],
    }


def documents():
    mcp = {
        'enabled': True,
        'servers': [
            {'id': 'github', 'transport': 'stdio', 'enabled': True,
             'url': 'https://stdio-ignored.test/${STDIO_URL_KEY}',
             'env': {'GITHUB_PERSONAL_ACCESS_TOKEN': '${ROOT_GITHUB_TOKEN}',
                     'api_key_env': 'LITERAL_MCP_VALUE'},
             'args': ['--token', '${ROOT_GITHUB_TOKEN}']},
            {'id': 'remote', 'transport': 'http',
             'headers': {'Authorization': 'Bearer ${ROOT_GITHUB_TOKEN}',
                         'X-MCP-Token': '${MCP_PRTS_WIKI_TOKEN}'},
             'env': {'HTTP_IGNorned': '${HTTP_ENV_KEY}'}},
            {'id': 'container', 'transport': 'docker',
             'docker_args': ['--env-file', '${DOCKER_ARG_KEY}']},
        ],
    }
    draft = {
        'providers': [provider('minimax', 'MINIMAX_API_KEY'),
                      provider('disabled', 'DRAFT_ONLY_KEY', enabled=False)],
        'settings': {'mcp': mcp},
        'style_profiles': {'default': 'Style ${STYLE_NAME:-fallback-secret}'},
    }
    published = {
        'providers': [provider('minimax', 'MINIMAX_API_KEY'),
                      provider('zhipu', 'ZHIPU_API_KEY')],
        'settings': {'mcp': mcp},
        'style_profiles': {'default': 'Style ${STYLE_NAME:-fallback-secret}'},
    }
    return [('draft', draft), ('published', published)]


def legacy_rows():
    return [
        {'name': 'MINIMAX_API_KEY', 'assigned': True, 'mode': 'credential',
         'references': ['minimax'], 'warning': '', 'states': {'bot': 'loaded'}},
        {'name': 'ROOT_ONLY', 'assigned': True, 'mode': 'unknown',
         'references': [], 'warning': '', 'states': {'bot': 'synced'}},
    ]


def write_generation(root, text=GENERATION):
    config = root / 'config'
    config.mkdir(exist_ok=True)
    (config / 'generation.toml').write_text(text)


def build(tmp_path):
    write_generation(tmp_path)
    return build_directory(tmp_path, documents(), legacy_rows())


def entry(result, name):
    return next(row for row in result['directory'] if row['name'] == name)


def test_shared_keys_have_one_row_and_consumer_specific_mechanisms(tmp_path):
    result = build(tmp_path)
    minimax = entry(result, 'MINIMAX_API_KEY')
    assert minimax['groups'] == ['services.native.generation', 'services.native.llm']
    assert minimax['states'] == {'bot': 'loaded'}
    assert len(minimax['relations']) == 7
    llm = [r for r in minimax['relations'] if r['component'] == 'llm.provider']
    assert {r['config_scope'] for r in llm} == {'draft', 'published'}
    assert all(r['required_action'] == 'publish' for r in llm if r['config_scope'] == 'draft')
    assert all(r['required_action'] == 'next_task'
               for r in llm if r['config_scope'] == 'published')
    generation = [r for r in minimax['relations'] if r['component'].startswith('generation.')]
    assert {r['component'] for r in generation} == {
        'generation.image', 'generation.audio', 'generation.music'}
    assert all(r['required_action'] == 'restart_or_recreate' for r in generation)
    assert all(r['observation'] == 'not_observed' for r in minimax['relations'])
    assert entry(result, 'ZHIPU_API_KEY')['groups'] == [
        'services.native.generation', 'services.native.llm']


def test_lifecycle_targets_and_computed_names_are_explicit(tmp_path):
    result = build(tmp_path)
    draft = entry(result, 'DRAFT_ONLY_KEY')['relations'][0]
    assert draft['required_action'] == 'publish'
    assert draft['enabled'] is False
    assert entry(result, 'DRAFT_ONLY_KEY')['states'] == {}
    github = entry(result, 'ROOT_GITHUB_TOKEN')['relations']
    targets = {(r['target_kind'], r['target_name'], r['delivery']) for r in github}
    assert ('environment_name', 'GITHUB_PERSONAL_ACCESS_TOKEN', 'child_env') in targets
    assert ('http_header', 'Authorization', 'http_header') in targets
    assert ('process_argument', 'args', 'process_argument') in targets
    computed = entry(result, 'KEY_SELECTOR')
    assert computed['evidence_flags'] == {'computed_name': True}
    assert computed['relations'][0]['name_kind'] == 'computed_name'
    assert entry(result, 'LOCAL_TTS_KEY')['relations'][0]['required'] is False
    assert entry(result, 'ROOT_ONLY')['groups'] == ['unknown.unidentified']


def test_transport_shapes_channel_classification_only_where_runtime_uses_it(tmp_path):
    result = build(tmp_path)
    stdio_url = entry(result, 'STDIO_URL_KEY')['relations'][0]
    assert stdio_url['target_kind'] == 'config_field'
    assert stdio_url['target_name'] == 'url'
    http_env = entry(result, 'HTTP_ENV_KEY')['relations'][0]
    assert http_env['target_kind'] == 'config_field'
    assert http_env['target_name'] == 'env'
    docker_arg = entry(result, 'DOCKER_ARG_KEY')['relations'][0]
    assert docker_arg['target_kind'] == 'process_argument'
    assert docker_arg['target_name'] == 'docker_args'
    assert entry(result, 'MCP_PRTS_WIKI_TOKEN')['relations'][0]['target_name'] == 'X-MCP-Token'


def test_nested_name_key_literals_never_become_directory_entries(tmp_path):
    result = build(tmp_path)
    names = {row['name'] for row in result['directory']}
    assert 'LITERAL_BODY_VALUE' not in names
    assert 'LITERAL_MCP_VALUE' not in names
    payload = json.dumps(result, ensure_ascii=False)
    assert 'private-sentinel' not in payload
    assert 'fallback-secret' not in payload


def test_directory_never_returns_source_values_or_defaults(tmp_path):
    result = build(tmp_path)
    parameter = entry(result, 'PROVIDER_PARAM')['relations'][0]
    assert parameter['raw_expression'] == '${PROVIDER_PARAM}'
    assert parameter['default_present'] is True
    assert entry(result, 'MODEL_KEY')['relations'][0]['target_kind'] == 'model_parameters'
    generation_header = entry(result, 'GENERATION_HEADER_KEY')['relations'][0]
    assert generation_header['target_kind'] == 'config_field'
    assert generation_header['target_name'] == 'X-Key'


def test_svg_section_interpolation_is_projected(tmp_path):
    result = build(tmp_path)
    svg = entry(result, 'SVG_SWITCH')
    assert svg['groups'] == ['services.native.generation']
    assert svg['relations'][0]['component'] == 'generation.svg'
    assert svg['relations'][0]['enabled'] is None


def test_generation_declared_enabled_follows_runtime_bool_semantics(tmp_path):
    write_generation(tmp_path, '''
[generation.image]
enabled = "false"
[[generation.image.providers]]
id = "off-image"
protocol = "minimax_images"
api_key_env = "OFF_IMAGE_KEY"

[generation.audio]
enabled = "yes"
[[generation.audio.providers]]
id = "on-audio"
protocol = "minimax_t2a_http"
api_key_env = "ON_AUDIO_KEY"
''')
    result = build_directory(tmp_path, [], [])
    off = entry(result, 'OFF_IMAGE_KEY')['relations'][0]
    assert off['enabled'] is False
    assert off['required_action'] == 'unknown'
    on = entry(result, 'ON_AUDIO_KEY')['relations'][0]
    assert on['enabled'] is True
    assert on['required_action'] == 'restart_or_recreate'


def test_padded_generation_api_key_env_follows_runtime_stripping(tmp_path):
    write_generation(tmp_path, '''
[generation.image]
enabled = true
[[generation.image.providers]]
id = "padded"
protocol = "minimax_images"
api_key_env = "  PADDED_KEY  "
''')
    result = build_directory(tmp_path, [], [])
    padded = entry(result, 'PADDED_KEY')
    assert padded['relations'][0]['name_kind'] == 'configured_name'
    assert padded['relations'][0]['raw_expression'] == 'PADDED_KEY'
    assert padded['relations'][0]['field_path'].endswith('.api_key_env')
    assert [row['name'] for row in result['directory']].count('PADDED_KEY') == 1


def test_disabled_models_do_not_report_next_task_activation(tmp_path):
    doc = {
        'providers': [{
            'id': 'mixed', 'protocol': 'openai', 'base_url': 'https://example.test/v1',
            'api_key_env': 'MIXED_KEY', 'default_model': 'on', 'enabled': True,
            'models': [
                {'model': 'on', 'parameters': {}, 'enabled': True},
                {'model': 'off', 'parameters': {'token': '${DISABLED_MODEL_TOKEN}'},
                 'enabled': False},
            ],
        }],
    }
    result = build_directory(tmp_path, [('published', doc)], [])
    relation = entry(result, 'DISABLED_MODEL_TOKEN')['relations'][0]
    assert relation['enabled'] is False
    assert relation['required_action'] == 'unknown'
    assert relation['target_name'] == 'off'


def test_malformed_llm_document_is_isolated_from_other_sources(tmp_path):
    good = {
        'providers': [{
            'id': 'good', 'protocol': 'openai', 'base_url': 'https://example.test/v1',
            'api_key_env': 'GOOD_KEY', 'default_model': 'm',
            'models': [{'model': 'm'}],
        }],
    }
    write_generation(tmp_path)
    result = build_directory(
        tmp_path, [('draft', {'providers': 3}), ('published', good)], [])
    assert {'component': 'llm', 'code': 'directory_source_unavailable'} in (
        result['directory_errors'])
    assert entry(result, 'GOOD_KEY')['relations'][0]['object_id'] == 'good'
    assert entry(result, 'MINIMAX_API_KEY')['groups'] == ['services.native.generation']


def test_undefined_dynamic_entries_inherit_legacy_metadata(tmp_path):
    write_generation(tmp_path)
    references = {'DRAFT_ONLY_KEY': ['disabled']}
    result = build_directory(
        tmp_path, documents(), legacy_rows(),
        warning_for_name=lambda name: 'deploy-affecting' if name == 'DRAFT_ONLY_KEY' else '',
        references=references,
        mode_for=lambda name: 'credential' if name in references else 'unknown')
    dynamic = entry(result, 'DRAFT_ONLY_KEY')
    assert dynamic['mode'] == 'credential'
    assert dynamic['references'] == ['disabled']
    assert dynamic['warning'] == 'deploy-affecting'
    assert dynamic['assigned'] is False


def test_generation_failure_is_sanitized_and_preserves_legacy_rows(tmp_path):
    write_generation(tmp_path, 'invalid = "private-sentinel')
    result = build_directory(tmp_path, documents(), legacy_rows())
    assert result['directory_errors'] == [
        {'component': 'generation', 'code': 'directory_source_unavailable'}]
    assert entry(result, 'MINIMAX_API_KEY')['states'] == {'bot': 'loaded'}
    assert 'private-sentinel' not in json.dumps(result)
