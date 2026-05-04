from __future__ import annotations

from pathlib import Path

from quickquip.common.persistence import load_json, save_json


class GameScores:
    """Simple JSON-file persistence for game win counts.

    File structure::

        {
          "<group_id>": {
            "<game_name>": {
              "<user_id>": <score>
            }
          }
        }

    Thread-safe for single-writer workloads (the bot's asyncio event loop).
    """

    def __init__(self, path: str = "data/game_scores.json"):
        self._path = Path(path)
        self._data: dict[str, dict[str, dict[str, int]]] = {}
        self._load()

    def _load(self) -> None:
        loaded = load_json(self._path)
        self._data = loaded if isinstance(loaded, dict) else {}

    def _save(self) -> None:
        save_json(self._path, self._data)

    def record_win(self, group_id: str, user_id: str, game_name: str) -> None:
        """Increment the win count for *user_id* in *game_name* (under *group_id*)."""
        gid = str(group_id)
        uid = str(user_id)
        self._data.setdefault(gid, {}).setdefault(game_name, {})
        scores = self._data[gid][game_name]
        scores[uid] = scores.get(uid, 0) + 1
        self._save()

    def get_scores(self, group_id: str, game_name: str) -> dict[str, int]:
        """Return ``{user_id: score}`` for *game_name* in *group_id*."""
        return dict(self._data.get(str(group_id), {}).get(game_name, {}))

    def get_leaderboard(
        self, group_id: str, game_name: str, top_n: int = 10
    ) -> list[tuple[str, int]]:
        """Return the top *top_n* (user_id, score) sorted descending."""
        scores = self.get_scores(group_id, game_name)
        sorted_scores = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        return sorted_scores[:top_n]
