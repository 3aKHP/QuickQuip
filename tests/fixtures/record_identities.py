
import pytest

from quickquip.app.identities import IdentitySnapshot, identities, web_identities
from quickquip.common.identity import IdentityEntry, IdentityIndex


def index(*entries):
    result = IdentityIndex(entries=list(entries))
    result._build_indexes()
    return result


@pytest.fixture
def snapshot(monkeypatch):
    snap = IdentitySnapshot(
        index(IdentityEntry("标准名", ["12345"], ["别名"], "")),
        {"12345": "名片", "23456": "未登记名片"},
    )
    monkeypatch.setattr(identities, "snapshot", lambda scope: snap)
    monkeypatch.setattr(web_identities, "snapshot", lambda scope: snap)
    return snap


def write_identity(path, name):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'people:\n  - canonical_name: "{name}"\n    qq_ids: ["12345"]\n', encoding="utf-8"
    )
