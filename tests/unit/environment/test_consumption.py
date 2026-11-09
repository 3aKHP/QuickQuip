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
'''


def provider(name, key, enabled=True):
    return {
        'id': name, 'protocol': 'openai', 'base_url': 'https://example.test/v1',
        'api_key_env': key, 'default_model': 'm', 'enabled': enabled,
        'headers': {'Authorization': f'Bearer ${{{key}}}', 'X-Secret': 'private-sentinel'},
        'parameters': {'extra_body': {'credential': '${PROVIDER_PARAM:-fallback-secret}'}},
        'models': [{'model': 'm', 'parameters': {'credential': '${MODEL_KEY}'}}],
    }


def documents():
    mcp = {
        'enabled': True,
        'servers': [
            {'id': 'github', 'transport': 'stdio', 'enabled': True,
             'env': {'GITHUB_PERSONAL_ACCESS_TOKEN': '${ROOT_GITHUB_TOKEN}'},
             'args': ['--token', '${ROOT_GITHUB_TOKEN}']},
            {'id': 'remote', 'transport': 'http',
             'headers': {'Authorization': 'Bearer ${ROOT_GITHUB_TOKEN}',
                         'X-MCP-Token': '${MCP_PRTS_WIKI_TOKEN}'}},
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


def build(tmp_path):
    config = tmp_path / 'config'
    config.mkdir()
    (config / 'generation.toml').write_text(GENERATION)
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
    targets = {
        (r['target_kind'], r['target_name'])
        for r in entry(result, 'ROOT_GITHUB_TOKEN')['relations']
    }
    assert ('environment_name', 'GITHUB_PERSONAL_ACCESS_TOKEN') in targets
    assert ('http_header', 'Authorization') in targets
    computed = entry(result, 'KEY_SELECTOR')
    assert computed['evidence_flags'] == {'computed_name': True}
    assert computed['relations'][0]['name_kind'] == 'computed_name'
    assert entry(result, 'LOCAL_TTS_KEY')['relations'][0]['required'] is False
    assert entry(result, 'ROOT_ONLY')['groups'] == ['unknown.unidentified']


def test_directory_never_returns_source_values_or_defaults(tmp_path):
    result = build(tmp_path)
    payload = json.dumps(result, ensure_ascii=False)
    assert 'private-sentinel' not in payload
    assert 'fallback-secret' not in payload
    parameter = entry(result, 'PROVIDER_PARAM')['relations'][0]
    assert parameter['raw_expression'] == '${PROVIDER_PARAM}'
    assert parameter['default_present'] is True
    assert entry(result, 'MODEL_KEY')['relations'][0]['target_kind'] == 'model_parameters'
    assert entry(result, 'MCP_PRTS_WIKI_TOKEN')['relations'][0]['target_name'] == 'X-MCP-Token'
    generation_header = entry(result, 'GENERATION_HEADER_KEY')['relations'][0]
    assert generation_header['target_kind'] == 'http_header'
    assert generation_header['target_name'] == 'X-Key'


def test_generation_failure_is_sanitized_and_preserves_legacy_rows(tmp_path):
    config = tmp_path / 'config'
    config.mkdir()
    (config / 'generation.toml').write_text('invalid = "private-sentinel')
    result = build_directory(tmp_path, documents(), legacy_rows())
    assert result['directory_errors'] == [
        {'component': 'generation', 'code': 'directory_source_unavailable'}]
    assert entry(result, 'MINIMAX_API_KEY')['states'] == {'bot': 'loaded'}
    assert 'private-sentinel' not in json.dumps(result)
