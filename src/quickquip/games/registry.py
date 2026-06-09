from __future__ import annotations

from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from time import time
from typing import Optional


@dataclass
class GameResult:
    """Result returned by a game's process() method.

    Attributes:
        reply: Reply text to send to the group.
        at_user_id: User ID to @mention in the reply (optional).
        finished: Whether the game session has ended.
        rate_limit_key: Rate limit bucket key for this interaction.
        rule_name: Rule name for stats / rule_switch tracking.
    """

    reply: str
    at_user_id: Optional[str] = None
    finished: bool = False
    rate_limit_key: str = "game_interaction"
    rule_name: str = "game_interaction"


class BaseGame(ABC):
    """Abstract base for interactive group games.

    Subclasses implement a specific game (e.g. number-bomb) and register
    with a :class:`GameRegistry`.

    Each game manages its own per-group sessions. The registry only ever
    calls :meth:`process` on the game that is currently active for a group.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable game name used in ``/game list`` output."""
        ...

    @property
    def aliases(self) -> list[str]:
        """Alternative short names (e.g. ``["bomb"]``).

        Users can start a game with ``/game start <alias>``.
        """
        return []

    def start(self, group_id: str, user_id: str, start_arg: str = "") -> str:
        """Begin a new game session in *group_id*.

        Args:
            group_id: The group where the game is being started.
            user_id: The user who issued the start command.
            start_arg: Optional argument from the start command (e.g. bet amount).

        Returns:
            The opening message to send to the group.
        """
        ...

    @abstractmethod
    def stop(self, group_id: str) -> Optional[str]:
        """Force-stop the active session in *group_id*.

        Returns:
            A closing message (e.g. the secret number), or ``None`` if no
            session was active.
        """
        ...

    @abstractmethod
    def process(
        self, group_id: str, user_id: str, text: str, now_ts: float
    ) -> Optional[GameResult]:
        """Process an incoming message for this game.

        The registry calls this only when *group_id* has an active session
        for this game.

        Args:
            group_id: Group ID.
            user_id: User ID of the message sender.
            text: Text content of the message.
            now_ts: Current Unix timestamp.

        Returns:
            A :class:`GameResult` with the reply and other metadata, or
            ``None`` if the message is not a valid game input (silently
            ignored).
        """
        ...

    def is_active(self, group_id: str) -> bool:
        """Return ``True`` if *group_id* has an active session."""
        raise NotImplementedError


class GameRegistry:
    """Central registry for :class:`BaseGame` instances.

    Tracks which game is active in each group and delegates incoming
    messages to the appropriate game's :meth:`~BaseGame.process` method.
    """

    def __init__(self, max_sessions: int = 1024):
        self._games: dict[str, BaseGame] = {}
        self._sessions: OrderedDict[str, tuple[str, float]] = OrderedDict()
        # _sessions maps group_id → (game_name, started_at_ts)
        self._max_sessions = max_sessions

    # ── game management ──────────────────────────────────────────────────

    def register(self, game: BaseGame) -> None:
        """Register a game so it appears in listings and can be started."""
        self._games[game.name] = game

    def find(self, name_or_alias: str) -> Optional[BaseGame]:
        """Look up a game by its :attr:`~BaseGame.name` or one of its :attr:`~BaseGame.aliases`."""
        query = name_or_alias.strip()
        for game in self._games.values():
            if query == game.name:
                return game
        for game in self._games.values():
            if query in game.aliases:
                return game
        return None

    def list_games(self) -> list[dict]:
        """Return a list of dicts describing each registered game."""
        return [
            {
                "name": g.name,
                "aliases": g.aliases,
            }
            for g in self._games.values()
        ]

    # ── session management ───────────────────────────────────────────────

    def start_game(
        self, group_id: str, user_id: str, game: BaseGame, start_arg: str = ""
    ) -> Optional[str]:
        """Begin *game* in *group_id* and record the session.

        Returns the opening message, or ``None`` if a session is already
        active in this group.
        """
        key = str(group_id)
        if key in self._sessions:
            return None
        reply = game.start(key, user_id, start_arg)
        # Only register the session if the game actually created one.
        # start() may return an error/usage message without initialising
        # internal state — in that case is_active() returns False.
        if not game.is_active(key):
            return reply
        self._sessions[key] = (game.name, time())
        self._touch(key)
        self._prune()
        return reply

    def stop_game(self, group_id: str) -> Optional[str]:
        """Force-stop the active game in *group_id*.

        Returns the closing message, or ``None`` if no game was active.
        """
        key = str(group_id)
        entry = self._sessions.pop(key, None)
        if entry is None:
            return None
        game_name, _ = entry
        game = self._games.get(game_name)
        if game is None:
            return None
        return game.stop(key)

    def get_active_game_name(self, group_id: str) -> Optional[str]:
        """Return the name of the active game, or ``None``."""
        entry = self._sessions.get(str(group_id))
        if entry is None:
            return None
        return entry[0]

    # ── message dispatch ─────────────────────────────────────────────────

    def process(
        self,
        group_id: str,
        user_id: str,
        text: str,
        now_ts: float | None = None,
    ) -> Optional[dict]:
        """Dispatch a group message to the active game in *group_id*.

        Returns a dict compatible with :func:`~quickquip.app.message_pipeline.resolve_reply`,
        or ``None`` if no game is active or the input is not a valid guess.
        """
        key = str(group_id)
        entry = self._sessions.get(key)
        if entry is None:
            return None
        game_name, _ = entry
        game = self._games.get(game_name)
        if game is None:
            self._sessions.pop(key, None)
            return None

        ts = time() if now_ts is None else now_ts
        result = game.process(key, str(user_id), text, ts)
        if result is None:
            return None

        # Build the reply dict in the same format as resolve_reply / chain_game
        reply_dict: dict = {
            "reply": result.reply,
            "rate_limit_key": result.rate_limit_key,
            "rule_name": result.rule_name,
            "trigger_kind": "rule",
            "trigger_reason": f"群游戏互动：{game_name}",
            "game_name": game_name,
        }
        if result.at_user_id:
            reply_dict["at_user_id"] = result.at_user_id

        if result.finished:
            self._sessions.pop(key, None)

        return reply_dict

    # ── internal helpers ─────────────────────────────────────────────────

    def _touch(self, key: str) -> None:
        if key in self._sessions:
            self._sessions.move_to_end(key)

    def _prune(self) -> None:
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)
