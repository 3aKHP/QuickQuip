"""python-dotenv semantics with portable, explicitly marked literal values."""
from io import StringIO
import os
from pathlib import Path
import re
import uuid

from dotenv.main import DotEnv
from dotenv.parser import parse_stream

DELETED = re.compile(r'^\s*# quickquip:deleted ([A-Za-z_][A-Za-z0-9_]*)\s*$', re.MULTILINE)
LITERAL = '# quickquip:literal'


def markers(content):
    """Return managed definitions and explicit deletions without resolving values."""
    managed, deleted = set(), set()
    for binding in parse_stream(StringIO(content)):
        if binding.key:
            if binding.original.string.rstrip().endswith(LITERAL):
                managed.add(binding.key)
            else:
                managed.discard(binding.key)
        elif not binding.error:
            match = DELETED.fullmatch(binding.original.string.strip())
            if match:
                deleted.add(match[1])
    return managed, deleted


def read_environment(content, *, override=True):
    # Let the dependency own quoting, duplicates, bare keys, malformed lines and
    # interpolation precedence. Sentinels shield only our marked literal bindings;
    # restoring them afterwards also preserves values referenced by later bindings.
    prefix = 'QUICKQUIP_LITERAL_' + uuid.uuid4().hex
    while prefix in content or any(prefix in value for value in os.environ.values()):
        prefix = 'QUICKQUIP_LITERAL_' + uuid.uuid4().hex
    restored, lines = {}, []
    for binding in parse_stream(StringIO(content)):
        if (binding.key and not binding.error
                and binding.original.string.rstrip().endswith(LITERAL)):
            token = prefix + '_' + str(len(restored)) + '_END'
            restored[token] = (binding.value or '').replace('$$', '$')
            lines.append(binding.key + '=' + token + '\n')
        else:
            lines.append(binding.original.string)
    values = DotEnv(None, stream=StringIO(''.join(lines)), override=override).dict()
    for name, value in values.items():
        if value is not None:
            for token, literal in restored.items():
                value = value.replace(token, literal)
            values[name] = value
    return values


def load_dotenv(path, *, override=False):
    # Keep python-dotenv's disabled-loading contract as well as external precedence.
    if os.environ.get('PYTHON_DOTENV_DISABLED', '').lower() in ('1', 'true', 't', 'yes', 'y'):
        return False
    path = Path(path)
    if not path.exists():
        return False
    values = read_environment(path.read_text(encoding='utf-8'), override=override)
    for name, value in values.items():
        if value is not None and (override or name not in os.environ):
            os.environ[name] = value
    return bool(values)
