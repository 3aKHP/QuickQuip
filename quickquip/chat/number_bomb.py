from __future__ import annotations

import random
from collections import OrderedDict
from dataclasses import dataclass
from time import time
from typing import Optional

from quickquip.chat.game_registry import BaseGame, GameResult


@dataclass(slots=True)
class NumberBombSession:
    secret: int
    min_range: int = 1
    max_range: int = 1000
    expires_at: float = 0.0
    started_by: str = ""


class NumberBombGame(BaseGame):
    """数字炸弹 (Number Bomb) game.

    The bot picks a secret number in [1, 1000]. Group members take turns
    guessing; the bot replies "大了" or "小了" and narrows the range.
    The player who guesses correctly wins. Sessions expire after 60 seconds
    of inactivity.
    """

    @property
    def name(self) -> str:
        return "数字炸弹"

    @property
    def aliases(self) -> list[str]:
        return ["bomb", "number_bomb"]

    def __init__(
        self,
        max_sessions: int = 1024,
        min_number: int = 1,
        max_number: int = 1000,
        timeout_seconds: int = 60,
    ):
        self._max_sessions = max_sessions
        self._min_number = min_number
        self._max_number = max_number
        self._timeout = timeout_seconds
        self._sessions: OrderedDict[str, NumberBombSession] = OrderedDict()

    # ── public API ───────────────────────────────────────────────────────

    def start(self, group_id: str, user_id: str) -> str:
        secret = random.randint(self._min_number, self._max_number)
        session = NumberBombSession(
            secret=secret,
            min_range=self._min_number,
            max_range=self._max_number,
            expires_at=time() + self._timeout,
            started_by=str(user_id),
        )
        self._sessions[str(group_id)] = session
        self._touch(str(group_id))
        self._prune()
        return (
            f"数字炸弹已就绪，范围 {self._min_number}-{self._max_number}，开始猜吧！"
        )

    def stop(self, group_id: str) -> Optional[str]:
        session = self._sessions.pop(str(group_id), None)
        if session is None:
            return None
        return f"数字是 {session.secret}"

    def is_active(self, group_id: str) -> bool:
        return str(group_id) in self._sessions

    def process(
        self, group_id: str, user_id: str, text: str, now_ts: float
    ) -> Optional[GameResult]:
        key = str(group_id)
        session = self._sessions.get(key)
        if session is None:
            return None

        # Check for timeout
        if now_ts > session.expires_at:
            secret = session.secret
            self._sessions.pop(key, None)
            return GameResult(
                reply=f"时间到！数字是 {secret}",
                finished=True,
                rule_name="number_bomb_timeout",
            )

        # Parse input
        try:
            guess = int(text.strip())
        except ValueError:
            # Not a number — silently ignored
            return None

        if guess < self._min_number or guess > self._max_number:
            return None

        if guess < session.secret:
            session.min_range = max(session.min_range, guess)
            session.expires_at = now_ts + self._timeout
            self._touch(key)
            return GameResult(
                reply=f"小了，范围 {session.min_range}-{session.max_range}",
                rule_name="number_bomb_hint",
            )

        if guess > session.secret:
            session.max_range = min(session.max_range, guess)
            session.expires_at = now_ts + self._timeout
            self._touch(key)
            return GameResult(
                reply=f"大了，范围 {session.min_range}-{session.max_range}",
                rule_name="number_bomb_hint",
            )

        # Correct guess
        self._sessions.pop(key, None)
        return GameResult(
            reply=f"炸了！数字就是 {session.secret}！",
            at_user_id=str(user_id),
            finished=True,
            rule_name="number_bomb_win",
        )

    # ── internal helpers ─────────────────────────────────────────────────

    def _touch(self, key: str) -> None:
        if key in self._sessions:
            self._sessions.move_to_end(key)

    def _prune(self) -> None:
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)
