import re
from typing import Optional

from quickquip.chat.chain_game import ChainGameDef, ChainGameManager


GOOD_GIRL_START_PATTERN = re.compile(r"^(.+?)是好(.+?)吗[？?]*$")
GOOD_GIRL_TIMEOUT_SECONDS = 60

# The canonical good-girl chain definition, kept here as the named reference
# and as the built-in example for the chain_games TOML format.
#
# Chain layout (odd-length → session ends automatically after bot's last reply):
#   "别"      — bot opens
#   "逗"      — user
#   "你"      — bot
#   "$1[0]"   — user sends the first character of the subject ("X是好Y吗" → group 1 = "X...")
#   "姐"      — bot
#   "笑"      — user
#   "了"      — bot
#   "句号|。"  — user sends "句号" or "。" (full-width period); pipe = OR
#   "🤣"      — bot ends the chain
GOOD_GIRL_CHAIN_DEF = ChainGameDef(
    name="good_girl_chain",
    trigger_pattern=GOOD_GIRL_START_PATTERN,
    chain_template=["别", "逗", "你", "$1[0]", "姐", "笑", "了", "句号|。", "🤣"],
    timeout_seconds=GOOD_GIRL_TIMEOUT_SECONDS,
    rate_limit_key="good_girl_chain_entry",
)


class GoodGirlChainManager:
    """Named wrapper around ChainGameManager for the built-in 好姐姐 chain.

    Preserves the original public API and legacy context format
    ``{"lead_char": <first char of subject>}`` so that existing callers
    (pipeline, tests) require no changes.
    """

    def __init__(
        self,
        timeout_seconds: int = GOOD_GIRL_TIMEOUT_SECONDS,
        max_sessions: int = 1024,
    ):
        def_obj = ChainGameDef(
            name=GOOD_GIRL_CHAIN_DEF.name,
            trigger_pattern=GOOD_GIRL_CHAIN_DEF.trigger_pattern,
            chain_template=GOOD_GIRL_CHAIN_DEF.chain_template,
            timeout_seconds=timeout_seconds,
            rate_limit_key=GOOD_GIRL_CHAIN_DEF.rate_limit_key,
        )
        self._mgr = ChainGameManager([def_obj], max_sessions=max_sessions)

    @property
    def sessions(self):
        """Proxy to the inner manager's session dict (backward compat for tests)."""
        return self._mgr.sessions

    def process(
        self,
        group_id: int | str,
        text: str,
        now_ts: float | None = None,
    ) -> Optional[dict]:
        result = self._mgr.process(group_id=group_id, text=text, now_ts=now_ts)
        if result is None:
            return None
        # Translate generic context to legacy format.
        # group 1 of the trigger is the subject ("X是好Y吗" → "X..."),
        # lead_char is its first character — same as the original $1[0] slot.
        groups = result.get("context", {}).get("groups", ())
        lead_char = groups[0][0] if groups and groups[0] else ""
        result["context"] = {"lead_char": lead_char}
        return result
