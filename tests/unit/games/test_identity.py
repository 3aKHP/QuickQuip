from __future__ import annotations

from pathlib import Path

import pytest

import quickquip.games.identity as games_identity
from quickquip.common.identity_sources import IdentityRepository

_GROUP = "12345"

_GLOBAL_YAML = (
    "people:\n"
    "  - canonical_name: 全局甲\n"
    "    qq_ids:\n"
    '      - "10001"\n'
    "  - canonical_name: 全局乙\n"
    "    qq_ids:\n"
    '      - "10002"\n'
)

_GROUP_YAML = (
    "people:\n"
    "  - canonical_name: 群内甲\n"
    "    qq_ids:\n"
    '      - "10001"\n'
)


def _make_repo(tmp_path: Path) -> IdentityRepository:
    tmp_path.joinpath("identities.yaml").write_text(_GLOBAL_YAML, encoding="utf-8")
    group_dir = tmp_path / _GROUP
    group_dir.mkdir()
    group_dir.joinpath("identities.yaml").write_text(_GROUP_YAML, encoding="utf-8")
    tmp_path.joinpath("stats.json").write_text(
        f'{{"{_GROUP}": {{"user_names": {{"10003": "昵称丙"}}}}}}',
        encoding="utf-8",
    )
    return IdentityRepository(
        path=tmp_path / "identities.yaml", stats_path=tmp_path / "stats.json"
    )


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> IdentityRepository:
    repository = _make_repo(tmp_path)
    monkeypatch.setattr(games_identity, "identities", repository)
    return repository


def test_group_canonical_wins_over_global(repo: IdentityRepository):
    """同一 QQ 在群内与全局都有登记时，群内 canonical_name 优先。"""
    assert games_identity.display_name(_GROUP, "10001") == "群内甲"


def test_global_canonical_when_group_silent(repo: IdentityRepository):
    """群内未登记的 QQ 回落到全局 canonical_name。"""
    assert games_identity.display_name(_GROUP, "10002") == "全局乙"


def test_group_nickname_fallback(repo: IdentityRepository):
    """两级登记都没有时，用群内活跃昵称。"""
    assert games_identity.display_name(_GROUP, "10003") == "昵称丙"


def test_qq_fallback_last_resort(repo: IdentityRepository):
    """全链落空时退回 QQ{号} 数字形态，与全仓展示惯例一致。"""
    assert games_identity.display_name(_GROUP, "10004") == "QQ10004"


def test_global_scope_without_group(repo: IdentityRepository):
    """无群上下文（如私聊查全局榜）只用全局索引，不叠群内条目与昵称。"""
    assert games_identity.display_name(None, "10001") == "全局甲"
    assert games_identity.display_name(None, "10003") == "QQ10003"


def test_display_resolver_batch(repo: IdentityRepository):
    """排行榜批量渲染走同一份快照，链条语义与逐条调用一致。"""
    name_of = games_identity.display_resolver(_GROUP)
    assert name_of("10001") == "群内甲"
    assert name_of("10002") == "全局乙"
    assert name_of("10003") == "昵称丙"
    assert name_of("10004") == "QQ10004"
