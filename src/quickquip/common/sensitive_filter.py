"""Sensitive content filter for LLM-bound traffic.

Two-tier word matching backed by an Aho-Corasick automaton:

- **block**: any hit short-circuits the LLM call (input side) or substitutes a
  canned fallback (output side). Use for content where letting the message
  through is itself a compliance/safety risk.
- **soft**: hits are logged for monitoring but the message is allowed to
  proceed. Use for noisy or context-sensitive terms where false positives
  would hurt UX more than the rare miss costs us.

The actual word list lives in ``config/sensitive_words.toml`` (gitignored).
The ``.example`` template ships only generic anti-fraud / anti-spam words so
the project remains shareable; deployers fill in their own jurisdiction-
specific terms following ``docs/admin/sensitive-filter.md``.

Hits are reported with a SHA-256 hash of the matched word, never the plain
text — log files themselves can otherwise become a compliance liability.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from hashlib import sha256
import logging
from pathlib import Path
import tomllib
from typing import Iterable

from quickquip.common.config_utils import as_dict
from quickquip.common.paths import CONFIG_SENSITIVE_WORDS_TOML


logger = logging.getLogger(__name__)


SENSITIVE_WORDS_TOML = CONFIG_SENSITIVE_WORDS_TOML

DEFAULT_BLOCK_REPLY = "这条消息我不太能接，换个话题吧。"
DEFAULT_OUTPUT_FALLBACK = "（这条回复被安全过滤拦下了，换个话题吧）"
SCRUB_PLACEHOLDER = "[内容已屏蔽]"


@dataclass(slots=True, frozen=True)
class ScanHit:
    category: str
    severity: str  # "block" | "soft"
    word_hash: str  # short SHA-256 prefix of the matched word
    start: int
    end: int


@dataclass(slots=True)
class ScanResult:
    hits: list[ScanHit] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(h.severity == "block" for h in self.hits)

    @property
    def has_soft(self) -> bool:
        return any(h.severity == "soft" for h in self.hits)

    def block_categories(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for h in self.hits:
            if h.severity == "block" and h.category not in seen:
                seen.add(h.category)
                ordered.append(h.category)
        return ordered


class _AhoCorasick:
    """Minimal Aho-Corasick automaton.

    Pure Python because the expected word list size (a few thousand entries)
    runs well under a millisecond per group message. Avoids adding a C
    extension dependency. If the word list ever grows past ~50k entries,
    swap to ``pyahocorasick`` here.
    """

    __slots__ = ("_goto", "_fail", "_output", "_built")

    def __init__(self) -> None:
        self._goto: list[dict[str, int]] = [{}]
        self._fail: list[int] = [0]
        # node_id -> list of (word, payload)
        self._output: list[list[tuple[str, object]]] = [[]]
        self._built = False

    def add(self, word: str, payload: object) -> None:
        if not word:
            return
        if self._built:
            raise RuntimeError("automaton frozen; rebuild instead of adding")
        node = 0
        for ch in word:
            nxt = self._goto[node].get(ch)
            if nxt is None:
                nxt = len(self._goto)
                self._goto.append({})
                self._fail.append(0)
                self._output.append([])
                self._goto[node][ch] = nxt
            node = nxt
        self._output[node].append((word, payload))

    def build(self) -> None:
        queue: deque[int] = deque()
        for ch, child in self._goto[0].items():
            self._fail[child] = 0
            queue.append(child)
        while queue:
            r = queue.popleft()
            for ch, child in self._goto[r].items():
                queue.append(child)
                state = self._fail[r]
                while state and ch not in self._goto[state]:
                    state = self._fail[state]
                self._fail[child] = self._goto[state].get(ch, 0)
                if self._fail[child] == child:
                    self._fail[child] = 0
                self._output[child].extend(self._output[self._fail[child]])
        self._built = True

    def search(self, text: str) -> Iterable[tuple[int, int, str, object]]:
        if not self._built:
            return
        node = 0
        for i, ch in enumerate(text):
            while node and ch not in self._goto[node]:
                node = self._fail[node]
            node = self._goto[node].get(ch, 0)
            for word, payload in self._output[node]:
                yield (i - len(word) + 1, i + 1, word, payload)


def _normalize(text: str) -> str:
    """Light normalization to make trivial obfuscation harder.

    - lowercase ASCII
    - drop a small set of zero-width / formatting chars commonly used to
      split keywords (e.g. inserting spaces or invisible chars between
      characters of a sensitive term)
    - collapse Unicode width via casefold

    We deliberately do NOT do full pinyin / homoglyph normalization here —
    that's a deeper rabbit hole and false positives explode. This layer is
    a tripwire, not a determined-adversary defense.
    """
    if not text:
        return ""
    cleaned: list[str] = []
    for ch in text.casefold():
        cp = ord(ch)
        # zero-width joiners / non-joiners / BOM / soft hyphen
        if cp in (0x200B, 0x200C, 0x200D, 0xFEFF, 0x00AD):
            continue
        # ASCII whitespace squeezed out so "六 四" still hits "六四"
        if ch in (" ", "\t"):
            continue
        cleaned.append(ch)
    return "".join(cleaned)


def _word_hash(word: str) -> str:
    return sha256(word.encode("utf-8")).hexdigest()[:12]


@dataclass(slots=True)
class _Payload:
    category: str
    severity: str


class SensitiveFilter:
    """Two-tier sensitive-word matcher backed by Aho-Corasick.

    Construct via :meth:`from_toml` (loads ``config/sensitive_words.toml``)
    or :meth:`empty` for tests / disabled deployments. Reload by calling
    :meth:`load_toml` — the previous automaton is replaced atomically so
    in-flight scans always see a consistent state.
    """

    __slots__ = ("_automaton", "_word_count", "_block_count", "_soft_count")

    def __init__(self) -> None:
        self._automaton = _AhoCorasick()
        self._automaton.build()
        self._word_count = 0
        self._block_count = 0
        self._soft_count = 0

    @classmethod
    def empty(cls) -> "SensitiveFilter":
        return cls()

    @classmethod
    def from_toml(cls, path: str | Path = SENSITIVE_WORDS_TOML) -> "SensitiveFilter":
        instance = cls()
        instance.load_toml(path)
        return instance

    def load_toml(self, path: str | Path) -> None:
        """Replace the in-memory automaton with words from ``path``.

        Missing file is treated as "no filtering configured" — the bot still
        runs, only without a sensitive-word tripwire. We log a warning so
        deployers notice if the file disappears unexpectedly.
        """
        config_path = Path(path)
        if not config_path.exists():
            logger.warning(
                "sensitive_filter: %s not found; running without word list",
                config_path,
            )
            self._replace(_AhoCorasick(), 0, 0, 0)
            return

        try:
            with config_path.open("rb") as fh:
                data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            logger.error("sensitive_filter: failed to load %s: %s", config_path, exc)
            return

        new_auto = _AhoCorasick()
        block = 0
        soft = 0
        seen: set[str] = set()

        def _extract_words(raw: object) -> list[str]:
            # Each category section in the TOML is `[block.fraud] words = [...]`
            # which tomllib parses as ``{"words": [...]}``. We accept either
            # the wrapped form or a bare list (older drafts may have used the
            # bare form).
            if isinstance(raw, list):
                return [str(item) for item in raw]
            if isinstance(raw, dict):
                inner = raw.get("words", [])
                if isinstance(inner, list):
                    return [str(item) for item in inner]
            return []

        block_section = as_dict(data.get("block"))
        for category, raw in block_section.items():
            for word_str in _extract_words(raw):
                word = _normalize(word_str)
                if not word or word in seen:
                    continue
                seen.add(word)
                new_auto.add(word, _Payload(category=str(category), severity="block"))
                block += 1

        soft_section = as_dict(data.get("soft"))
        for category, raw in soft_section.items():
            for word_str in _extract_words(raw):
                word = _normalize(word_str)
                if not word or word in seen:
                    continue
                seen.add(word)
                new_auto.add(word, _Payload(category=str(category), severity="soft"))
                soft += 1

        new_auto.build()
        self._replace(new_auto, block + soft, block, soft)
        logger.info(
            "sensitive_filter: loaded %d block, %d soft from %s",
            block, soft, config_path,
        )

    def _replace(
        self,
        new_auto: _AhoCorasick,
        word_count: int,
        block_count: int,
        soft_count: int,
    ) -> None:
        self._automaton = new_auto
        self._word_count = word_count
        self._block_count = block_count
        self._soft_count = soft_count

    @property
    def is_loaded(self) -> bool:
        return self._word_count > 0

    @property
    def stats(self) -> dict[str, int]:
        return {
            "total": self._word_count,
            "block": self._block_count,
            "soft": self._soft_count,
        }

    def scan(self, text: str) -> ScanResult:
        result = ScanResult()
        if not text or not self._word_count:
            return result
        normalized = _normalize(text)
        if not normalized:
            return result
        seen_keys: set[tuple[int, int, str]] = set()
        for start, end, word, payload in self._automaton.search(normalized):
            assert isinstance(payload, _Payload)
            key = (start, end, word)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            result.hits.append(
                ScanHit(
                    category=payload.category,
                    severity=payload.severity,
                    word_hash=_word_hash(word),
                    start=start,
                    end=end,
                )
            )
        return result

    def scrub(self, text: str, placeholder: str = SCRUB_PLACEHOLDER) -> str:
        """Replace block-level matches in ``text`` with ``placeholder``.

        Used by history-side cleanup so a previously-stored message that the
        current word list now considers blocked won't pollute the next LLM
        request. Indices come from the normalized form, so we re-run scan
        on the normalized text and rebuild from there. Soft hits are not
        scrubbed — that tier is for monitoring only.
        """
        if not text or not self._word_count:
            return text
        normalized = _normalize(text)
        result = self.scan(text)
        if not result.blocked:
            return text
        # Sort hits by start, merge overlaps, then rebuild from the
        # normalized string. We accept that the output uses normalized
        # casing/whitespace for the surviving fragments — the alternative
        # is mapping normalized indices back to original indices, which
        # gets fiddly when zero-widths were stripped. For LLM-history use
        # the normalized form is fine.
        block_spans = sorted(
            ((h.start, h.end) for h in result.hits if h.severity == "block"),
            key=lambda s: s[0],
        )
        if not block_spans:
            return text
        merged: list[tuple[int, int]] = []
        cur_start, cur_end = block_spans[0]
        for s, e in block_spans[1:]:
            if s <= cur_end:
                cur_end = max(cur_end, e)
            else:
                merged.append((cur_start, cur_end))
                cur_start, cur_end = s, e
        merged.append((cur_start, cur_end))

        out: list[str] = []
        cursor = 0
        for s, e in merged:
            out.append(normalized[cursor:s])
            out.append(placeholder)
            cursor = e
        out.append(normalized[cursor:])
        return "".join(out)


# Module-level singleton, lazy-loaded on first import by the app layer.
_INSTANCE: SensitiveFilter | None = None


def get_filter() -> SensitiveFilter:
    """Return the process-wide filter, building it on first call."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = SensitiveFilter.from_toml(SENSITIVE_WORDS_TOML)
    return _INSTANCE


def reload_filter() -> SensitiveFilter:
    """Force reload from disk; useful after editing the word list."""
    global _INSTANCE
    _INSTANCE = SensitiveFilter.from_toml(SENSITIVE_WORDS_TOML)
    return _INSTANCE


def log_hits(channel: str, scope: str, result: ScanResult) -> None:
    """Emit a hit summary at WARNING/INFO level without leaking matched text.

    ``channel`` is one of "input"/"output"/"history". ``scope`` is the
    chat scope key (group id or "private:USER_ID"). We log category +
    word hash so on-call can correlate spikes without the log file itself
    becoming a sensitive artifact.
    """
    if not result.hits:
        return
    block_summary = [
        f"{h.category}:{h.word_hash}" for h in result.hits if h.severity == "block"
    ]
    soft_summary = [
        f"{h.category}:{h.word_hash}" for h in result.hits if h.severity == "soft"
    ]
    if block_summary:
        logger.warning(
            "sensitive_filter[%s] blocked scope=%s hits=%s",
            channel, scope, ",".join(block_summary),
        )
    elif soft_summary:
        logger.info(
            "sensitive_filter[%s] soft-flagged scope=%s hits=%s",
            channel, scope, ",".join(soft_summary),
        )
