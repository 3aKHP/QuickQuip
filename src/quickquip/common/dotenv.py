"""Root dotenv evaluation matching Compose's literal single-quoted values."""
from io import StringIO
import os
from pathlib import Path
import re

from dotenv.parser import parse_stream
from dotenv.variables import parse_variables


def read_environment(content):
    values = {}
    for binding in parse_stream(StringIO(content)):
        if binding.error:
            raise ValueError('Invalid dotenv syntax')
        if binding.key is None:
            continue
        value = binding.value or ''
        single_quoted = re.match(
            r"\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=\s*'", binding.original.string,
        )
        if binding.original.string.rstrip().endswith('# quickquip:literal'):
            value = value.replace('$$', '$')
        elif not single_quoted:
            value = ''.join(part.resolve(values) for part in parse_variables(value))
        values[binding.key] = value
    return values


def load_dotenv(path, *, override=False):
    path = Path(path)
    if not path.exists():
        return False
    for name, value in read_environment(path.read_text(encoding='utf-8')).items():
        if override or name not in os.environ:
            os.environ[name] = value
    return True
