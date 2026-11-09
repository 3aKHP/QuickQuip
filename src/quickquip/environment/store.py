"""Versioned, recoverable root environment edits; public results contain metadata only."""
from contextlib import contextmanager
from io import StringIO
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import time

from quickquip.common.dotenv import DELETED, markers, read_environment
from quickquip.common.config_writes import configuration_write, write_lock
from quickquip.configuration.text import parse
from quickquip.llm.config_durability import durable_write

NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
HOT = {'TIEBA_FORUM_KEYWORD', 'TIEBA_FORUM_KEYWORDS'}


class EnvironmentError(ValueError):
    pass


def mode(name, references=()):
    if name in HOT:
        return 'hot'
    if name in references:
        return 'credential'
    return 'restart'


def warning(name):
    if name == 'QUICKQUIP_ENV_MANAGEMENT_ENABLED':
        return '管理开关在进程启动时读取；修改后需重启 Bot 和 Web Admin。'
    if name.startswith(('QUICKQUIP_DEPLOY_', 'PYTHON', 'LD_', 'COMPOSE_', 'DOCKER_')):
        return '修改会影响后续部署或进程执行环境，请确认目标和恢复方式。'
    if name.startswith(('WEB_ADMIN_', 'ONEBOT_', 'HOST', 'PORT', 'DRIVER')):
        return '修改可能影响登录、连接或访问；当前进程保持运行，重启后生效。'
    return ''


def literal(name, value):
    # The marker keeps source startup literal too; Compose consumes $$ as a literal $.
    return name + '=' + json.dumps(value.replace('$', '$$'), ensure_ascii=False) + (
        ' # quickquip:literal\n'
    )


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.directory = self.root / 'data/environment'
        self.path = self.root / '.env'

    def _json(self, name, default):
        p = self.directory / name
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default

    def _own(self, path):
        if hasattr(os, 'geteuid') and os.geteuid() == 0 and self.path.exists():
            owner = self.path.stat()
            os.chown(path, owner.st_uid, owner.st_gid)

    def _write(self, name, value):
        path = self.directory / name
        durable_write(path, json.dumps(value, ensure_ascii=False).encode())
        self._own(path)

    def _recover(self):
        journal = self._json('active.json', None)
        if journal:
            # Persist the intended complete file before the metadata; repeating either
            # replacement after a crash is safe and never restores a committed old key.
            candidate = (self.directory / 'candidate.env').read_bytes()
            current = self.path.read_bytes() if self.path.exists() else b''
            if (hashlib.sha256(current).hexdigest() != journal['before']
                    and current != candidate):
                raise EnvironmentError(
                    'Environment changed during recovery; inspect private journal'
                )
            self._replace(candidate)
            self._write('state.json', journal['state'])
            self._write('operations.json', journal['operations'])
            (self.directory / 'active.json').unlink()
            from quickquip.llm.config_durability import sync_directory
            sync_directory(self.directory)
            (self.directory / 'candidate.env').unlink(missing_ok=True)

    def _replace(self, data):
        if self.path.is_symlink():
            raise EnvironmentError('Root environment must be a regular file')
        before = self.path.stat() if self.path.exists() else None
        durable_write(self.path, data)
        if before:
            os.chmod(self.path, before.st_mode & 0o777)
            if hasattr(os, 'chown'):
                os.chown(self.path, before.st_uid, before.st_gid)

    def _state(self):
        state = self._json('state.json', {'salt': secrets.token_hex(32)})
        raw = self.path.read_bytes() if self.path.exists() else b''
        version = hmac.new(state['salt'].encode(), raw, hashlib.sha256).hexdigest()
        if state.get('version') != version:
            state.update(version=version)
            self._write('state.json', state)
        return state, raw

    def _values(self, raw, state):
        return read_environment(raw.decode('utf-8'))

    @contextmanager
    def _guard(self, action):
        if action in ('preview', 'changes'):
            from quickquip.common.config_writes import maintenance_owner
            with maintenance_owner('environment'), configuration_write(self.root / 'data'):
                yield
            return
        directory = self.root / 'data/config-sync'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with write_lock(directory.resolve()):
            marker = directory / 'maintenance.json'
            if marker.exists() and not json.loads(
                marker.read_text(encoding='utf-8')
            ).get('allow_start', False):
                raise EnvironmentError('Configuration installation is in progress')
            if (self.root / 'data/qqconf/active.json').exists():
                raise EnvironmentError('Recover the interrupted configuration write first')
            yield

    def execute(self, action, body=None):
        body = body or {}
        with self._guard(action):
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._own(self.directory)
            self._recover()
            state, raw = self._state()
            if action == 'initialize':
                self._adopt_deletions(state, raw)
                return {'initialized': True}
            if action == 'snapshot':
                managed, deleted = markers(raw.decode('utf-8'))
                return {'version': state['version'], 'values': self._values(raw, state),
                        'managed': sorted(managed), 'deleted': sorted(deleted)}
            if action == 'list':
                return self._listing(state, raw)
            if action == 'ack':
                role = body['role']
                if role not in ('bot', 'web'):
                    raise EnvironmentError('Invalid consumer')
                ack = {k: body[k] for k in
                       ('role', 'version', 'boot_id', 'updated_at', 'names')}
                old = self._json(role + '.json', {})
                if 'startup_values' in body:
                    ack['_startup'] = {name: self._fingerprint(state, True, value)
                                       for name, value in body['startup_values'].items()}
                elif old.get('boot_id') == ack['boot_id']:
                    ack['_startup'] = old.get('_startup', {})
                self._write(role + '.json', ack)
                return {'acknowledged': True}
            if action in ('operation', 'retry'):
                operations = self._json('operations.json', {})
                result = operations.get(body.get('id'))
                if result is None:
                    raise EnvironmentError('Operation not found')
                from quickquip.environment.policy import provider_references
                references = provider_references(self.root)
                rows = [{**row, 'mode': mode(row['name'], references),
                         'references': references.get(row['name'], [])}
                        for row in result['changes']]
                current = self._values(raw, state)
                superseded = any(
                    digest != self._fingerprint(state, name in current, current.get(name, ''))
                    for name, digest in result.get('_desired', {}).items()
                )
                return {**{k: v for k, v in result.items() if not k.startswith('_')},
                        'changes': rows, 'phase': 'superseded' if superseded else result['phase'],
                        'consumers': self._consumers(),
                        'states': self._statuses(state, raw, rows)}
            if action not in ('preview', 'changes'):
                raise EnvironmentError('Unknown environment operation')
            if action == 'changes':
                operations = self._json('operations.json', {})
                previous = operations.get(body.get('request_id'))
                if previous:
                    digest = hmac.new(state['salt'].encode(),
                                      json.dumps(body.get('changes', []), sort_keys=True).encode(),
                                      hashlib.sha256).hexdigest()
                    if previous.get('_digest') != digest:
                        raise EnvironmentError('Request ID already used for different changes')
                    return {k: v for k, v in previous.items() if not k.startswith('_')}
            if body.get('expected_version') != state['version']:
                raise EnvironmentError('Environment changed; refresh before saving')
            operations = self._json('operations.json', {})
            request_id = body.get('request_id', '')
            if action == 'changes' and not ID.fullmatch(request_id):
                raise EnvironmentError('Invalid request ID')
            if action == 'changes' and request_id in operations:
                raise EnvironmentError('Request already submitted; query its operation ID')
            candidate, changed = self._candidate(raw, body.get('changes', []))
            result = {'id': request_id, 'phase': 'saved', 'changes': changed}
            if action == 'preview':
                return result
            state['version'] = hmac.new(
                state['salt'].encode(), candidate, hashlib.sha256
            ).hexdigest()
            result.update(version=state['version'], saved_at=time.time())
            operations[request_id] = {**result, '_digest': hmac.new(
                state['salt'].encode(),
                json.dumps(body.get('changes', []), sort_keys=True).encode(),
                hashlib.sha256).hexdigest()}
            desired = read_environment(candidate.decode())
            operations[request_id]['_desired'] = {
                row['name']: self._fingerprint(
                    state, row['name'] in desired, desired.get(row['name'], '')
                ) for row in changed
            }
            self._commit(state, raw, candidate, operations)
            return {**result, 'consumers': self._consumers(),
                    'states': self._statuses(state, candidate, changed)}

    def _commit(self, state, raw, candidate, operations):
        state['version'] = hmac.new(
            state['salt'].encode(), candidate, hashlib.sha256
        ).hexdigest()
        durable_write(self.directory / 'candidate.env', candidate)
        self._own(self.directory / 'candidate.env')
        self._write('active.json', {'state': state, 'operations': operations,
                                    'before': hashlib.sha256(raw).hexdigest()})
        self._recover()

    def _adopt_deletions(self, state, raw):
        # Only confirmed last operations qualify. A definition restored manually
        # or by configuration sync takes precedence over historical operations.
        operations = self._json('operations.json', {})
        last = {}
        for operation in sorted(operations.values(), key=lambda item: item.get('saved_at', 0)):
            for change in operation.get('changes', []):
                last[change['name']] = change['action']
        values = parse('.env', raw)
        _, deleted = markers(raw.decode('utf-8'))
        adopted = sorted(name for name, action in last.items()
                         if action == 'delete' and name not in values and name not in deleted)
        if adopted:
            prefix = b'\n' if raw and not raw.endswith(b'\n') else b''
            candidate = raw + prefix + ''.join(
                '# quickquip:deleted ' + name + '\n' for name in adopted
            ).encode()
            self._commit(state, raw, candidate, operations)

    @staticmethod
    def _fingerprint(state, present, value):
        return hmac.new(state['salt'].encode(), json.dumps([present, value]).encode(),
                        hashlib.sha256).hexdigest()

    def _consumers(self):
        result = {}
        for role in ('bot', 'web'):
            ack = self._json(role + '.json', None)
            result[role] = ({k: v for k, v in ack.items() if not k.startswith('_')}
                            if ack else None)
        return result

    def _statuses(self, state, raw, rows):
        values = self._values(raw, state)
        statuses = {}
        for row in rows:
            name = row['name']
            statuses[name] = {}
            for role in ('bot', 'web'):
                ack = self._json(role + '.json', None)
                if not ack or time.time() - ack['updated_at'] > 20:
                    status = 'waiting'
                elif row['mode'] != 'restart':
                    status = 'loaded' if ack['version'] == state['version'] else 'loading'
                else:
                    startup = ack.get('_startup', {})
                    expected = self._fingerprint(state, name in values, values.get(name, ''))
                    actual = startup.get(name, self._fingerprint(state, False, ''))
                    status = 'loaded' if expected == actual else 'restart'
                statuses[name][role] = status
        return statuses

    def _listing(self, state, raw):
        values = self._values(raw, state)
        from quickquip.environment.policy import provider_references
        references = provider_references(self.root)
        rows = [
            {'name': name, 'assigned': bool(value), 'mode': mode(name, references),
             'references': references.get(name, []), 'warning': warning(name)}
            for name, value in sorted(values.items())]
        statuses = self._statuses(state, raw, rows)
        example = self.root / '.env.example'
        if not example.exists():
            example = Path('/app/.env.example')
        suggestions = (sorted(set(read_environment(example.read_text(encoding='utf-8')))
                              - set(values)) if example.exists() else [])
        return {'version': state['version'], 'suggestions': suggestions,
                'variables': [{**row, 'states': statuses[row['name']]} for row in rows],
                'consumers': self._consumers()}

    def _candidate(self, raw, changes):
        from dotenv.parser import parse_stream
        if not isinstance(changes, list) or not changes or len(changes) > 256:
            raise EnvironmentError('Submit between 1 and 256 changes')
        old = parse('.env', raw)
        _, deleted = markers(raw.decode('utf-8'))
        from quickquip.environment.policy import provider_references
        references = provider_references(self.root)
        edits = {}
        descriptions = []
        for item in changes:
            name, op = item.get('name', ''), item.get('action')
            if not isinstance(name, str) or not NAME.fullmatch(name) or name in edits:
                raise EnvironmentError('Invalid or duplicate variable name')
            if op not in ('create', 'replace', 'empty', 'delete'):
                raise EnvironmentError('Invalid edit action')
            if (op == 'create') == (name in old and name not in deleted):
                raise EnvironmentError('Variable existence changed: ' + name)
            value = '' if op == 'empty' else item.get('value', '')
            if not isinstance(value, str) or '\x00' in value or len(value) > 65536:
                raise EnvironmentError('Invalid value for ' + name)
            value = value.replace('\r\n', '\n').replace('\r', '\n')
            choices = {'QUICKQUIP_DEPLOY_LOCATION': {'local', 'cloud'},
                       'QUICKQUIP_DEPLOY_RUNTIME': {'source', 'docker'}}
            if op != 'delete' and name in choices and value and value not in choices[name]:
                raise EnvironmentError('Invalid deployment mode for ' + name)
            edits[name] = None if op == 'delete' else literal(name, value)
            descriptions.append({'name': name, 'action': op, 'mode': mode(name, references),
                                 'references': references.get(name, []),
                                 'warning': warning(name)})
        output = []
        seen = set()
        for binding in parse_stream(StringIO(raw.decode())):
            key = binding.key
            if key is None:
                match = DELETED.fullmatch(binding.original.string.strip())
                if match:
                    key = match[1]
            if key not in edits:
                output.append(binding.original.string)
            elif key not in seen:
                output.append(edits[key] or '# quickquip:deleted ' + key + '\n')
                seen.add(key)
        if output and not output[-1].endswith('\n'):
            output.append('\n')
        output.extend(
            value or '# quickquip:deleted ' + key + '\n'
            for key, value in edits.items() if key not in seen
        )
        candidate = ''.join(output).replace('\r\n', '\n').encode()
        parse('.env', candidate)
        resolved = read_environment(candidate.decode())
        for item in changes:
            if item['action'] in ('create', 'replace'):
                expected = item.get('value', '').replace('\r\n', '\n').replace('\r', '\n')
                if resolved[item['name']] != expected:
                    raise EnvironmentError('Value cannot be represented in dotenv')
        return candidate, descriptions
