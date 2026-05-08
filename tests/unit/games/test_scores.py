from __future__ import annotations

from quickquip.games.scores import GameScores


def test_record_win_and_leaderboard(tmp_path):
    store = GameScores(tmp_path / "game_scores.json")

    store.record_win("g1", "u2", "bomb")
    store.record_win("g1", "u1", "bomb")
    store.record_win("g1", "u2", "bomb")

    assert store.get_scores("g1", "bomb") == {"u1": 1, "u2": 2}
    assert store.get_leaderboard("g1", "bomb") == [("u2", 2), ("u1", 1)]
