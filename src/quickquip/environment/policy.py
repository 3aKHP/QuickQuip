"""Classify only credential consumers whose hot loading is implemented."""
import json
from pathlib import Path
import re
import sqlite3


def read_llm_documents(root):
    root = Path(root)
    documents = []
    for scope, relative, query in (
        ('draft', 'config/managed/config.db', 'SELECT document FROM config_meta'),
        ('published', 'data/config_runtime.db', 'SELECT document FROM execution_snapshots '
         'JOIN publication ON revision=published_revision'),
    ):
        path = root / relative
        if not path.exists():
            continue
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as connection:
            documents.extend((scope, json.loads(row[0])) for row in connection.execute(query))
    return documents


def provider_references(root, documents=None):
    if documents is None:
        documents = read_llm_documents(root)
    references = {}
    for _, document in documents:
        for provider in document.get('providers', []):
            names = {provider.get('api_key_env', '')}
            for value in provider.get('headers', {}).values():
                names.update(re.findall(r'\$\{([A-Za-z_][A-Za-z0-9_]*)', value))
            for name in names - {''}:
                references.setdefault(name, set()).add(provider['id'])
    return {name: sorted(owners) for name, owners in references.items()}
