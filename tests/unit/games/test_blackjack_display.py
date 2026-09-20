"""21 点调用点的显示名渲染覆盖（PR #256 Bot Review SHOULD-FIX）。

打桩身份仓库后驱动真实对局流程，断言发牌/结算文案含解析后的显示名且
不再出现 ``QQ:`` 裸号前缀——防止未来调用点回退或漏改。
"""
from __future__ import annotations

from pathlib import Path
from time import time

import pytest

import quickquip.games.identity as games_identity
from quickquip.common.identity_sources import IdentityRepository
from quickquip.games.blackjack import BlackjackGame

_GROUP = "12345"

_GROUP_YAML = (
    "people:\n"
    "  - canonical_name: 庄家甲\n"
    "    qq_ids:\n"
    '      - "10001"\n'
    "  - canonical_name: 闲家乙\n"
    "    qq_ids:\n"
    '      - "10002"\n'
)


@pytest.fixture()
def game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BlackjackGame:
    tmp_path.joinpath("identities.yaml").write_text("", encoding="utf-8")
    group_dir = tmp_path / _GROUP
    group_dir.mkdir()
    group_dir.joinpath("identities.yaml").write_text(_GROUP_YAML, encoding="utf-8")
    tmp_path.joinpath("stats.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        games_identity,
        "identities",
        IdentityRepository(
            path=tmp_path / "identities.yaml", stats_path=tmp_path / "stats.json"
        ),
    )
    return BlackjackGame()


def test_blackjack_flow_renders_display_names_without_bare_qq(game: BlackjackGame):
    game.start(_GROUP, "10001", "40")
    join = game.process(_GROUP, "10002", "入场 20", time())
    assert join is not None
    assert "QQ:" not in join.reply
    assert "闲家乙" in join.reply

    replies = []
    for uid, text in (("10001", "开局"), ("10001", "结束")):
        result = game.process(_GROUP, uid, text, time())
        if result is not None:
            replies.append(result.reply)
    final = "\n".join(replies)

    assert "QQ:" not in final
    assert "庄家甲" in final
    assert "闲家乙" in final
