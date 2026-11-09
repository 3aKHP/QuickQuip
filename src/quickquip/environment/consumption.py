"""Read-only environment consumption projection; never exposes configuration values."""
import copy
import json
from pathlib import Path
import tomllib

from quickquip.generation.config import (
    generation_api_key_required,
    generation_environment_sections,
)
from quickquip.llm.config_document import environment_occurrences


TAXONOMY = [
    {'id': 'runtime', 'label': '运行与内置功能', 'groups': [
        {'id': 'runtime.bot', 'label': 'Bot与连接'},
        {'id': 'runtime.admin', 'label': '管理与会话'},
        {'id': 'runtime.tieba', 'label': '贴吧'},
        {'id': 'runtime.trace', 'label': 'Trace'},
        {'id': 'runtime.framework', 'label': '框架与系统'},
    ]},
    {'id': 'services', 'label': '服务与扩展', 'groups': [
        {'id': 'services.native.llm', 'label': '原生接入 / LLM'},
        {'id': 'services.native.generation', 'label': '原生接入 / 多模态生成'},
        {'id': 'services.native.search', 'label': '原生接入 / 搜索'},
        {'id': 'services.external.mcp', 'label': '外部扩展 / MCP'},
    ]},
    {'id': 'deployment', 'label': '部署与构建', 'groups': [
        {'id': 'deployment.connection', 'label': '部署连接'},
        {'id': 'deployment.image', 'label': '镜像与依赖'},
    ]},
    {'id': 'unknown', 'label': '待识别', 'groups': [
        {'id': 'unknown.unidentified', 'label': '待确认'},
    ]},
]

_PROVIDER_FIXED = (
    'id', 'protocol', 'base_url', 'api_key_env', 'default_model', 'enabled',
    'client_fingerprint', 'headers', 'fallback_urls', 'proxy', 'auth_method',
)


def _literal_id(value):
    return value if isinstance(value, str) and '${' not in value else None


def _enabled(*values):
    if all(type(value) is bool for value in values):
        return all(values)
    return None


def _action(scope, enabled, active):
    if scope == 'draft':
        return 'publish'
    return active if enabled is not False else 'unknown'


def _target(path, transport=''):
    parts = path.split('.')
    key = parts[-1]
    if '.headers.' in path:
        if transport and transport not in ('http', 'sse'):
            return 'config_field', 'headers', 'config_value'
        return 'http_header', key, 'http_header'
    if '.env.' in path:
        delivery = 'child_env' if transport == 'stdio' else (
            'docker_env' if transport == 'docker' else 'config_value')
        return 'environment_name', key, delivery
    if key == 'url':
        return 'url', 'url', 'url'
    if key in ('args', 'docker_args') or '.args[' in path or '.docker_args[' in path:
        return 'process_argument', key, 'process_argument'
    return 'config_field', key, 'config_value'


def _relation(component, group, occurrence, scope, *, object_id, enabled, required,
              action, resolution, target_service='bot', target_kind=None,
              target_name=None, delivery='config_value', source_kind):
    path = occurrence['path']
    computed = path.endswith('.api_key_env') and occurrence['kind'] == 'interpolation'
    name_kind = 'computed_name' if computed else occurrence['kind']
    relation = {
        'component': component,
        'object_id': object_id,
        'field_path': path,
        'config_scope': scope,
        'enabled': enabled,
        'required': required,
        'name_kind': name_kind,
        'source_name': occurrence['name'],
        'raw_expression': occurrence['raw_expression'],
        'target_service': target_service,
        'target_kind': target_kind,
        'target_name': target_name,
        'resolution': resolution,
        'delivery': delivery,
        'required_action': action,
        'observation': 'not_observed',
    }
    if occurrence['default_present']:
        relation['default_present'] = True
    source = {
        'kind': source_kind,
        'context': scope,
        'path': path,
        'raw_expression': occurrence['raw_expression'],
        'resolution_context': resolution,
        'evidence_scope': 'config',
        'observation': 'not_observed',
    }
    return group, relation, source


def _provider_usages(scope, provider, index):
    base = f'providers[{index}]'
    enabled = provider.get('enabled', True)
    enabled = enabled if type(enabled) is bool else None
    object_id = _literal_id(provider.get('id'))
    for key in _PROVIDER_FIXED:
        if key not in provider:
            continue
        occurrences = environment_occurrences({key: provider[key]}, path=base)
        for occurrence in occurrences:
            next_task = key in ('api_key_env', 'headers')
            target_kind, target_name, delivery = _target(occurrence['path'])
            if key == 'api_key_env':
                target_kind, target_name, delivery = (
                    'environment_name', occurrence['name'], 'provider_credential')
            yield _relation(
                'llm.provider', 'services.native.llm', occurrence, scope,
                object_id=object_id, enabled=enabled,
                required=True if key == 'api_key_env' else None,
                action=_action(scope, enabled, 'next_task' if next_task else 'apply'),
                resolution='managed_snapshot' if next_task else 'llm_config',
                target_kind=target_kind, target_name=target_name,
                delivery=delivery, source_kind='llm_config')
    if isinstance(provider.get('parameters'), dict):
        for occurrence in environment_occurrences(
                provider['parameters'], path=f'{base}.parameters'):
            yield _relation(
                'llm.provider', 'services.native.llm', occurrence, scope,
                object_id=object_id, enabled=enabled, required=None,
                action=_action(scope, enabled, 'apply'), resolution='llm_config',
                target_kind='config_field', target_name='parameters',
                source_kind='llm_config')
    for model_index, model in enumerate(provider.get('models', []) or []):
        if not isinstance(model, dict) or not isinstance(model.get('parameters'), dict):
            continue
        path = f'{base}.models[{model_index}].parameters'
        for occurrence in environment_occurrences(model['parameters'], path=path):
            yield _relation(
                'llm.provider', 'services.native.llm', occurrence, scope,
                object_id=object_id, enabled=enabled, required=None,
                action=_action(scope, enabled, 'next_task'), resolution='managed_snapshot',
                target_kind='model_parameters',
                target_name=_literal_id(model.get('model')), source_kind='llm_config')


def _mcp_usages(scope, mcp):
    global_enabled = mcp.get('enabled', False)
    for index, server in enumerate(mcp.get('servers', []) or []):
        if not isinstance(server, dict):
            continue
        enabled = _enabled(global_enabled, server.get('enabled', True))
        transport = server.get('transport', 'stdio')
        for occurrence in environment_occurrences(
                server, path=f'settings.mcp.servers[{index}]'):
            target_kind, target_name, delivery = _target(occurrence['path'], transport)
            yield _relation(
                'mcp.server', 'services.external.mcp', occurrence, scope,
                object_id=_literal_id(server.get('id')), enabled=enabled, required=None,
                action=_action(scope, enabled, 'apply'), resolution='llm_config',
                target_service='mcp', target_kind=target_kind, target_name=target_name,
                delivery=delivery, source_kind='llm_config')


def _style_usages(scope, profiles):
    if not isinstance(profiles, dict):
        return
    for profile_id, value in profiles.items():
        for occurrence in environment_occurrences(value, path=f'style_profiles.{profile_id}'):
            yield _relation(
                'llm.style_profile', 'services.native.llm', occurrence, scope,
                object_id=profile_id, enabled=None, required=None,
                action='publish' if scope == 'draft' else 'apply', resolution='llm_config',
                target_kind='style_profile', target_name=profile_id,
                source_kind='llm_config')


def _llm_usages(documents):
    for scope, document in documents:
        if not isinstance(document, dict):
            continue
        for index, provider in enumerate(document.get('providers', []) or []):
            if isinstance(provider, dict):
                yield from _provider_usages(scope, provider, index)
        settings = document.get('settings', {})
        if isinstance(settings, dict) and isinstance(settings.get('mcp'), dict):
            yield from _mcp_usages(scope, settings['mcp'])
        yield from _style_usages(scope, document.get('style_profiles', {}))


def _generation_usages(root):
    path = root / 'config/generation.toml'
    if not path.exists():
        return [], []
    try:
        with path.open('rb') as stream:
            data = tomllib.load(stream)
        sections = generation_environment_sections(data)
        usages = []
        for item in sections:
            modality = item['modality']
            section = item['section']
            base = item['path']
            raw_enabled = section.get('enabled', False)
            enabled = raw_enabled if type(raw_enabled) is bool else None
            providers = section.get('providers', [])
            for index, provider in enumerate(providers if isinstance(providers, list) else []):
                if not isinstance(provider, dict):
                    continue
                for occurrence in environment_occurrences(
                        provider, path=f'{base}.providers[{index}]'):
                    direct = occurrence['kind'] == 'configured_name'
                    api_key = occurrence['path'].endswith('.api_key_env')
                    target_kind, target_name, delivery = _target(occurrence['path'])
                    if direct:
                        target_kind = 'environment_name'
                        target_name = occurrence['name']
                        delivery = 'provider_credential'
                    usages.append(_relation(
                        f'generation.{modality}', 'services.native.generation',
                        occurrence, 'file', object_id=_literal_id(provider.get('id')),
                        enabled=enabled,
                        required=(generation_api_key_required(
                            modality, provider.get('protocol', '')) if api_key else None),
                        action='restart_or_recreate' if enabled is not False else 'unknown',
                        resolution='process' if direct else 'generation_config',
                        target_kind=target_kind,
                        target_name=target_name,
                        delivery=delivery,
                        source_kind='generation_file'))
            remainder = {key: value for key, value in section.items() if key != 'providers'}
            for occurrence in environment_occurrences(remainder, path=base):
                usages.append(_relation(
                    f'generation.{modality}', 'services.native.generation',
                    occurrence, 'file', object_id=None, enabled=enabled, required=None,
                    action='restart_or_recreate' if enabled is not False else 'unknown',
                    resolution='generation_config', target_kind='config_field',
                    target_name=occurrence['path'].split('.')[-1],
                    source_kind='generation_file'))
        return usages, []
    except (OSError, ValueError, TypeError, RecursionError, tomllib.TOMLDecodeError):
        return [], [{'component': 'generation', 'code': 'directory_source_unavailable'}]


def _deduplicate(items):
    result = []
    seen = set()
    for item in items:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def build_directory(root, documents, legacy_rows, warning_for_name=None):
    root = Path(root)
    warning_for_name = warning_for_name or (lambda name: '')
    usages = list(_llm_usages(documents))
    generation, errors = _generation_usages(root)
    usages.extend(generation)
    entries = {}
    for row in legacy_rows:
        entries[row['name']] = {
            'name': row['name'], 'assigned': row['assigned'], 'mode': row['mode'],
            'references': row['references'], 'warning': row['warning'],
            'states': row['states'], 'groups': [], 'relations': [], 'sources': [],
            'evidence_flags': {},
        }
    for group, relation, source in usages:
        name = relation['source_name']
        entry = entries.setdefault(name, {
            'name': name, 'assigned': False, 'mode': 'unknown', 'references': [],
            'warning': warning_for_name(name), 'states': {},
            'groups': [], 'relations': [], 'sources': [], 'evidence_flags': {},
        })
        if group not in entry['groups']:
            entry['groups'].append(group)
        entry['relations'].append(relation)
        entry['sources'].append(source)
        if relation['name_kind'] == 'computed_name':
            entry['evidence_flags']['computed_name'] = True
    for entry in entries.values():
        entry['groups'].sort()
        if not entry['groups']:
            entry['groups'] = ['unknown.unidentified']
        entry['relations'] = _deduplicate(entry['relations'])
        entry['sources'] = _deduplicate(entry['sources'])
    return {
        'taxonomy': copy.deepcopy(TAXONOMY),
        'directory': [entries[name] for name in sorted(entries)],
        'directory_errors': errors,
    }
