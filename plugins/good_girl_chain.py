import re
from dataclasses import dataclass
from time import time
from typing import Optional


GOOD_GIRL_START_PATTERN = re.compile(r"^(.+?)是好(.+?)吗[？?]*$")
GOOD_GIRL_TIMEOUT_SECONDS = 60


@dataclass
class GoodGirlSession:
    lead_char: str
    expires_at: float
    next_index: int = 0


class GoodGirlChainManager:
    def __init__(self, timeout_seconds: int = GOOD_GIRL_TIMEOUT_SECONDS):
        self.timeout_seconds = timeout_seconds
        self.sessions: dict[str, GoodGirlSession] = {}

    def _now(self, now_ts: float | None = None) -> float:
        return time() if now_ts is None else now_ts

    def _clear_if_expired(self, group_key: str, now_ts: float) -> None:
        session = self.sessions.get(group_key)
        if session and now_ts > session.expires_at:
            self.sessions.pop(group_key, None)

    def _build_chain(self, lead_char: str) -> list[str]:
        return ["别", "逗", "你", lead_char, "姐", "笑", "了", "🤣"]

    def _advance_session(self, session: GoodGirlSession, heard_text: str) -> Optional[str]:
        chain = self._build_chain(session.lead_char)
        if session.next_index >= len(chain) - 1:
            return None

        expected_token = chain[session.next_index]
        if heard_text != expected_token:
            return None

        session.next_index += 1
        return chain[session.next_index]

    def process(
        self,
        group_id: int | str,
        text: str,
        now_ts: float | None = None,
    ) -> Optional[dict]:
        normalized_text = text.strip()
        if not normalized_text:
            return None

        current_ts = self._now(now_ts)
        group_key = str(group_id)
        self._clear_if_expired(group_key, current_ts)

        session = self.sessions.get(group_key)
        if session is not None:
            if normalized_text == "🤣":
                self.sessions.pop(group_key, None)
                return None

            next_token = self._advance_session(session, normalized_text)
            if next_token is None:
                return None

            if next_token == "🤣":
                self.sessions.pop(group_key, None)
            else:
                session.expires_at = current_ts + self.timeout_seconds

            return {
                "reply": next_token,
                "rate_limit_key": "good_girl_chain_entry",
                "rule_name": "good_girl_chain_progress",
                "context": {"lead_char": session.lead_char},
            }

        start_match = GOOD_GIRL_START_PATTERN.fullmatch(normalized_text)
        if not start_match:
            return None

        lead_char = start_match.group(1)[0]
        self.sessions[group_key] = GoodGirlSession(
            lead_char=lead_char,
            expires_at=current_ts + self.timeout_seconds,
        )
        return {
            "reply": "别",
            "rate_limit_key": "good_girl_chain_entry",
            "rule_name": "good_girl_chain_start",
            "context": {"lead_char": lead_char},
        }
