import re
from collections import OrderedDict
from dataclasses import dataclass
from time import time
from typing import Optional

# Matches $N or $N[idx], e.g. $1, $2[-1], $1[0]
_REF_RE = re.compile(r"\$(\d+)(?:\[(-?\d+)\])?")


def _matches_token(text: str, token: str) -> bool:
    """Return True if *text* matches *token*, supporting pipe-separated alternatives.

    ``"句号|。"`` matches either ``"句号"`` or ``"。"``.
    Plain tokens (no ``|``) behave as exact equality checks.
    """
    return text in token.split("|")


def _resolve_ref(template: str, groups: tuple[str, ...]) -> str:
    """Replace $N / $N[idx] placeholders with capture group text.

    $1       → full text of group 1
    $1[0]    → first character of group 1
    $1[-1]   → last character of group 1
    $1[2]    → character at index 2 of group 1
    Out-of-range group numbers are left as-is; out-of-range character
    indices fall back to the full group text.
    """
    def replace(m: re.Match) -> str:
        n = int(m.group(1))
        if n < 1 or n > len(groups):
            return m.group(0)
        text = groups[n - 1]
        idx_str = m.group(2)
        if idx_str is not None:
            try:
                return text[int(idx_str)]
            except IndexError:
                return text
        return text

    return _REF_RE.sub(replace, template)


def _resolve_chain(templates: list[str], groups: tuple[str, ...]) -> list[str]:
    return [_resolve_ref(t, groups) for t in templates]


@dataclass
class ChainGameDef:
    """Definition of a regex-triggered chain game.

    Chain layout (0-indexed):
      chain[0]           — bot's opening reply
      chain[1], [3], … — tokens the user must send (odd indices)
      chain[2], [4], … — bot's replies (even indices ≥ 2)

    Odd-length chain  (e.g. length 7): session ends automatically after the
    last bot reply (no terminal token required from the user).

    Even-length chain (e.g. length 8): the last element (chain[n-1]) is a
    silent terminal token — sending it at any point ends the session without
    a bot reply.  This mirrors the original 好姐姐 "🤣" behaviour.

    chain_template may contain $N / $N[idx] placeholders resolved at
    session-start time against the trigger match's capture groups.
    """

    name: str
    trigger_pattern: re.Pattern
    chain_template: list[str]
    timeout_seconds: int = 60
    rate_limit_key: str = "good_girl_chain_entry"

    @classmethod
    def from_dict(cls, data: dict) -> "ChainGameDef":
        return cls(
            name=data["name"],
            trigger_pattern=re.compile(data["trigger_pattern"]),
            chain_template=list(data["chain"]),
            timeout_seconds=int(data.get("timeout_seconds", 60)),
            rate_limit_key=str(data.get("rate_limit_key", "good_girl_chain_entry")),
        )


@dataclass
class ChainGameSession:
    def_name: str
    chain: list[str]        # fully resolved at session-start time
    groups: tuple           # raw capture groups from the trigger match
    expires_at: float
    next_index: int = 1     # always points to the next expected user token


class ChainGameManager:
    """Manages multiple chain game definitions with one active session per group.

    When a group has no active session, the first matching def's trigger
    pattern starts a new session.  Only one chain can be active per group
    at a time (first-match-wins on concurrent triggers).
    """

    def __init__(
        self,
        defs: list[ChainGameDef],
        max_sessions: int = 1024,
    ):
        self.defs = list(defs)
        self.max_sessions = max_sessions
        self.sessions: OrderedDict[str, ChainGameSession] = OrderedDict()

    def replace_defs(self, defs: list[ChainGameDef]) -> None:
        """Swap in a new set of chain-game definitions and drop any in-flight sessions."""
        self.defs = list(defs)
        self.sessions.clear()

    # ── internal helpers ──────────────────────────────────────────────────

    def _now(self, now_ts: float | None) -> float:
        return time() if now_ts is None else now_ts

    def _touch(self, key: str) -> None:
        if key in self.sessions:
            self.sessions.move_to_end(key)

    def _prune(self) -> None:
        while len(self.sessions) > self.max_sessions:
            self.sessions.popitem(last=False)

    def _clear_expired(self, key: str, now_ts: float) -> None:
        s = self.sessions.get(key)
        if s and now_ts > s.expires_at:
            self.sessions.pop(key, None)

    def _get_def(self, name: str) -> Optional[ChainGameDef]:
        return next((d for d in self.defs if d.name == name), None)

    # ── public API ────────────────────────────────────────────────────────

    def process(
        self,
        group_id: int | str,
        text: str,
        now_ts: float | None = None,
    ) -> Optional[dict]:
        normalized = text.strip()
        if not normalized:
            return None

        current_ts = self._now(now_ts)
        key = str(group_id)
        self._clear_expired(key, current_ts)

        session = self.sessions.get(key)
        if session is not None:
            self._touch(key)
            def_obj = self._get_def(session.def_name)
            timeout = def_obj.timeout_seconds if def_obj else 60
            rate_limit_key = def_obj.rate_limit_key if def_obj else "good_girl_chain_entry"
            chain = session.chain
            n = len(chain)

            # Even-length chains: last element is a silent terminal token.
            # Sending it at any point during the session ends it immediately.
            if n % 2 == 0 and _matches_token(normalized, chain[n - 1]):
                self.sessions.pop(key, None)
                return None

            # Guard: next_index is past the end, or there is no bot reply slot.
            if session.next_index >= n or session.next_index + 1 >= n:
                return None

            if not _matches_token(normalized, chain[session.next_index]):
                return None

            reply = chain[session.next_index + 1]
            session.next_index += 2

            if session.next_index >= n:
                # Odd-length: we just issued the last bot reply — session over.
                self.sessions.pop(key, None)
            else:
                session.expires_at = current_ts + timeout

            return {
                "reply": reply,
                "rate_limit_key": rate_limit_key,
                "rule_name": f"{session.def_name}_progress",
                "trigger_kind": "rule",
                "trigger_reason": f"接龙规则推进：{session.def_name}",
                "context": {"groups": session.groups},
            }

        # ── no active session: try to start one ──────────────────────────
        for def_obj in self.defs:
            m = def_obj.trigger_pattern.fullmatch(normalized)
            if m is None:
                continue

            groups = m.groups()
            chain = _resolve_chain(def_obj.chain_template, groups)
            if not chain:
                continue

            self.sessions[key] = ChainGameSession(
                def_name=def_obj.name,
                chain=chain,
                groups=groups,
                expires_at=current_ts + def_obj.timeout_seconds,
                next_index=1,
            )
            self._touch(key)
            self._prune()

            return {
                "reply": chain[0],
                "rate_limit_key": def_obj.rate_limit_key,
                "rule_name": f"{def_obj.name}_start",
                "trigger_kind": "rule",
                "trigger_reason": f"接龙规则开始：{def_obj.name}",
                "context": {"groups": groups},
            }

        return None
