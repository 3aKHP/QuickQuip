"""Citation-only display projection; coordinates always refer to saved text."""
from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlsplit


_LINK = re.compile(r"\[([^\]\n]*)\]\((https?://(?:[^()\s]|\([^()\s]*\))+)\)")
_URL = re.compile(r"https?://(?:[^\s<>\[\]（），。；！？：、()\"']|\([^()\s]*\))+")
_CODE = re.compile(r"```[^\n]*\n.*?(?:```|\Z)|~~~[^\n]*\n.*?(?:~~~|\Z)|`[^`\n]+`", re.S)
_SOURCE_HEADER = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]+)?(?:\*\*|__)?"
    r"(?:来源|参考来源|参考资料|Sources|References)[：:]?"
    r"(?:\*\*|__)?[：:]?[ \t]*\n"
)
_STUB = re.compile(r"(?:来源|参考|source|\d+|(?:www\.)?[\w-]+(?:\.[\w-]+)+(?:/[^\s]*)?)", re.I)


@dataclass(frozen=True, slots=True)
class DisplayProjection:
    text: str
    # Original index of each retained character. Display edits are deletions only.
    positions: tuple[int, ...]
    source_length: int
    hidden_ranges: tuple[tuple[int, int], ...] = ()

    def boundary(self, offset: int) -> int:
        """Assign hidden prefixes/tails to the adjacent visible chunk."""
        if offset == 0:
            return 0
        if offset == len(self.text):
            return self.source_length
        return self.positions[offset]


def _overlaps(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start < b and a < end for a, b in ranges)


def _merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _source_entry(candidate: str) -> bool:
    if _LINK.fullmatch(candidate) or _URL.fullmatch(candidate):
        return True
    urls = list(_URL.finditer(candidate))
    if len(urls) != 1:
        return False
    url = urls[0]
    prefix, suffix = candidate[:url.start()].rstrip(), candidate[url.end():].strip()
    if not prefix or (prefix[-1], suffix) not in {("(", ")"), ("（", "）")}:
        return False
    label = prefix[:-1].strip()
    return bool(label) and not re.search(r"[。！？!?\n]", label)


def _citation_ranges(fragment: str, offset: int) -> list[tuple[int, int]]:
    """Remove URLs and citation scaffolding, retaining substantive link labels."""
    ranges: list[tuple[int, int]] = []
    links = list(_LINK.finditer(fragment))
    for link in links:
        label = link.group(1)
        try:
            host = urlsplit(link.group(2)).hostname or ""
        except ValueError:
            host = ""
        if not label or _STUB.fullmatch(label.strip()) or label.strip() == host:
            ranges.append(link.span())
        else:
            ranges.extend([(link.start(), link.start(1)), (link.end(1), link.end())])
    for url in _URL.finditer(fragment):
        if _overlaps(*url.span(), [m.span() for m in links]):
            continue
        start, end = url.span()
        # Parentheses are URL data only when balanced within the URL.
        while end > start and fragment[end - 1] in ".,;，。；":
            end -= 1
        while end > start and fragment[end - 1] == ")" and (
            fragment[start:end].count(")") > fragment[start:end].count("(")
        ):
            end -= 1
        ranges.append((start, end))
    if not ranges:
        # A separate opaque-marker label range supplied by the protocol parser.
        if _STUB.fullmatch(fragment.strip()):
            return [(offset, offset + len(fragment))]
        return []
    # Grow around now-empty parentheses/brackets and pure source labels.
    mask = [False] * len(fragment)
    for start, end in ranges:
        mask[start:end] = [True] * (end - start)
    remaining = "".join(c for i, c in enumerate(fragment) if not mask[i])
    stub = remaining.strip(" \t\n()（）[]【】,，;；:：-—")
    if not stub:
        return [(offset, offset + len(fragment))]
    # Match wrapper pairs, ignoring deleted URL syntax; never pair '(' with ']'.
    stack: list[int] = []
    pairs = {"(": ")", "（": "）", "[": "]", "【": "】"}
    for index, char in enumerate(fragment):
        if mask[index]:
            continue
        if char in pairs:
            stack.append(index)
        elif stack and pairs[fragment[stack[-1]]] == char:
            start = stack.pop()
            if all(mask[i] or fragment[i].isspace() for i in range(start + 1, index)):
                mask[start:index + 1] = [True] * (index + 1 - start)
    result = []
    start = None
    for index, removed in enumerate([*mask, False]):
        if removed and start is None:
            start = index
        elif not removed and start is not None:
            result.append((offset + start, offset + index))
            start = None
    return result


def project_citations(
    text: str,
    citation_spans: list[tuple[int, int]] | tuple[tuple[int, int], ...] = (),
    *,
    generated_tail_start: int | None = None,
) -> DisplayProjection:
    """Project confirmed citations and unambiguous source lists; preserve normal links."""
    code = [m.span() for m in _CODE.finditer(text)]
    hidden: list[tuple[int, int]] = []
    # Numbered/source-labelled references, or parenthesized domain citations.
    # An ordinary named action link (even one also in search sources) is untouched.
    for link in _LINK.finditer(text):
        if _overlaps(*link.span(), code):
            continue
        label = link.group(1).strip()
        explicit = re.fullmatch(r"\d+|来源|参考|source", label, re.I)
        parenthesized = (
            link.start() > 0 and link.end() < len(text)
            and (text[link.start() - 1], text[link.end()]) in {("(", ")"), ("（", "）")}
        )
        if explicit or (parenthesized and _STUB.fullmatch(label)):
            hidden.extend(_citation_ranges(link.group(), link.start()))
    for start, end in citation_spans:
        if type(start) is int and type(end) is int and 0 <= start < end <= len(text):
            hidden.extend(
                (a, b) for a, b in _citation_ranges(text[start:end], start)
                if not _overlaps(a, b, code)
            )
    if generated_tail_start is not None and 0 <= generated_tail_start <= len(text):
        hidden.append((generated_tail_start, len(text)))
    # A source heading alone conveys no authority: consume only link-only list lines.
    for header in _SOURCE_HEADER.finditer(text):
        if _overlaps(*header.span(), code):
            continue
        cursor = header.end()
        count = 0
        while cursor < len(text):
            end = text.find("\n", cursor)
            end = len(text) if end < 0 else end + 1
            line = text[cursor:end]
            candidate = re.sub(r"^\s*(?:[-*•]|\d+[.)、])\s*", "", line).strip()
            is_link = _source_entry(candidate)
            if not is_link or _overlaps(cursor, end, code):
                break
            count += 1
            cursor = end
        if count:
            hidden.append((header.start(), cursor))
    hidden = _merge(hidden)
    # Enclose a removed standalone citation with its immediately adjacent wrappers.
    expanded: list[tuple[int, int]] = []
    for start, end in hidden:
        left, right = start, end
        while left > 0 and text[left - 1] in " \t":
            left -= 1
        while right < len(text) and text[right] in " \t":
            right += 1
        if left and right < len(text) and (text[left - 1], text[right]) in {
            ("(", ")"), ("（", "）"), ("[", "]"), ("【", "】"),
        }:
            start, end = left - 1, right + 1
        expanded.append((start, end))
    hidden = _merge(expanded)
    positions: list[int] = []
    cursor = 0
    for start, end in hidden:
        positions.extend(range(cursor, start))
        cursor = end
    positions.extend(range(cursor, len(text)))
    # Citation-only tails should not leave blank messages or trailing whitespace.
    if hidden:
        while positions and text[positions[-1]].isspace():
            positions.pop()
        first = 0
        while first < len(positions) and text[positions[first]].isspace():
            first += 1
        positions = positions[first:]
    return DisplayProjection("".join(text[i] for i in positions), tuple(positions), len(text),
                             tuple(hidden))
