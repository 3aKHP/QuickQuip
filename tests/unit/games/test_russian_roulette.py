from pathlib import Path

from quickquip.games.economy import GameEconomyStore
from quickquip.games.registry import GameRegistry
from quickquip.games.russian_roulette import RussianRouletteGame


def test_failed_accept_cleans_session_and_refunds_acceptor(tmp_path: Path) -> None:
    store = GameEconomyStore(str(tmp_path / "economy.db"))
    store.add_gold("starter", "group", 100)
    store.add_gold("acceptor", "group", 100)
    game = RussianRouletteGame(economy=store)
    registry = GameRegistry()
    registry.register(game)

    registry.start_game("group", "starter", game, "20")
    registry.process("group", "starter", "1", 0)
    store.deduct_gold("starter", "group", 90)

    result = registry.process("group", "acceptor", "接受对决", 1)

    assert result is not None
    assert result["reply"] == "发起者金币不足，对决取消"
    assert registry.get_active_game_name("group") is None
    assert not game.is_active("group")
    assert store.get_balance("starter", "group")["gold"] == 10
    assert store.get_balance("acceptor", "group")["gold"] == 100


def test_start_usage_message_does_not_register_session(tmp_path: Path) -> None:
    store = GameEconomyStore(str(tmp_path / "economy.db"))
    store.add_gold("starter", "group", 100)
    game = RussianRouletteGame(economy=store)
    registry = GameRegistry()
    registry.register(game)

    reply = registry.start_game("group", "starter", game, "")

    assert reply is not None
    assert reply.startswith("用法：/game start 俄罗斯轮盘")
    assert registry.get_active_game_name("group") is None
    assert not game.is_active("group")
