from __future__ import annotations

from pathlib import Path

from plugins.llm_identity import IdentityIndex

from tests.fixtures.configs import IDENTITIES_YAML


def _write_and_load(tmp_path: Path) -> IdentityIndex:
    path = tmp_path / "identities.yaml"
    path.write_text(IDENTITIES_YAML, encoding="utf-8")
    return IdentityIndex.from_file(path)


def test_resolve_user_known_qq(tmp_path: Path):
    idx = _write_and_load(tmp_path)
    match = idx.resolve_user("2002", sender_name="临时显示名")
    assert match.is_registered is True
    assert match.canonical_name == "镜子"
    assert match.user_id == "2002"
    assert match.sender_name == "临时显示名"
    assert "哈基镜" in match.aliases


def test_resolve_user_second_person(tmp_path: Path):
    idx = _write_and_load(tmp_path)
    match = idx.resolve_user("4004")
    assert match.is_registered is True
    assert match.canonical_name == "4s"
    assert "Туманность" in match.aliases


def test_resolve_user_unknown_qq(tmp_path: Path):
    idx = _write_and_load(tmp_path)
    match = idx.resolve_user("99999", sender_name="路人")
    assert match.is_registered is False
    assert match.canonical_name == ""
    assert match.user_id == "99999"
    assert match.sender_name == "路人"


def test_render_mention(tmp_path: Path):
    idx = _write_and_load(tmp_path)
    assert idx.render_mention("2002") == "@镜子"
    assert idx.render_mention("99999") == "@QQ99999"


def test_search_by_alias(tmp_path: Path):
    idx = _write_and_load(tmp_path)
    hits = idx.search("哈基镜", limit=5)
    assert hits
    assert hits[0].canonical_name == "镜子"


def test_search_by_qq(tmp_path: Path):
    idx = _write_and_load(tmp_path)
    hits = idx.search("4004", limit=5)
    assert hits
    assert hits[0].canonical_name == "4s"


def test_search_empty_query(tmp_path: Path):
    idx = _write_and_load(tmp_path)
    assert idx.search("   ") == []
