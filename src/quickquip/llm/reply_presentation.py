"""Prepare saved reply text and a separate citation-free delivery projection."""
from __future__ import annotations

from bisect import bisect_left
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import re
from typing import Any

from quickquip.llm.citation_display import DisplayProjection, project_citations
from quickquip.llm.provider.base import LLMResponse, strip_leading_reasoning_content
from quickquip.llm.rendering import append_web_search_source_block


@dataclass(frozen=True, slots=True)
class PreparedReply:
    text: str
    display: DisplayProjection
    presentation: dict[str, Any] | None = None


def plain_reply(text: str) -> PreparedReply:
    return PreparedReply(text, DisplayProjection(text, tuple(range(len(text))), len(text)))


def prepare_reply(response: LLMResponse, *, empty_placeholder: str = "") -> PreparedReply:
    raw = response.text or ""
    cleaned = strip_leading_reasoning_content(raw)
    offset = len(raw.rstrip()) - len(cleaned)
    positions = list(range(offset, offset + len(cleaned)))
    # Exactly mirror the existing canonical newline cleanup, retaining raw offsets.
    discard: set[int] = set()
    for match in re.finditer(r"\n{3,}", cleaned):
        discard.update(range(match.start() + 2, match.end()))
    positions = [p for i, p in enumerate(positions) if i not in discard]
    text = "".join(raw[p] for p in positions)
    if not text:
        text = empty_placeholder
        positions = []
    spans = []
    for start, end in getattr(response, "citation_spans", ()):
        if type(start) is int and type(end) is int and 0 <= start < end <= len(raw):
            spans.append((bisect_left(positions, start), bisect_left(positions, end)))
    tail_start = None
    report = getattr(response, "web_search", None)
    if report is not None and text:
        appended = append_web_search_source_block(text, report)
        if appended != text:
            tail_start = len(text)
            text = appended
    display = project_citations(text, spans, generated_tail_start=tail_start)
    metadata = None
    if report is not None or spans or display.hidden_ranges:
        metadata = {
            "version": 1,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "citation_spans": [list(span) for span in spans],
            "hidden_ranges": [list(span) for span in display.hidden_ranges],
            "display_text": display.text,
            "generated_tail_start": tail_start,
            "search": None if report is None else {
                "queries": list(report.queries),
                "sources": [{"title": s.title, "url": s.url} for s in report.sources],
                "raw_metadata": deepcopy(report.raw_metadata),
            },
        }
    return PreparedReply(text, display, metadata)


def validate_presentation(value: dict[str, Any], text: str) -> None:
    """Validate new persisted presentation records against their canonical text."""
    if (not isinstance(value, dict) or type(value.get("version")) is not int
            or value["version"] != 1
            or value.get("text_sha256") != hashlib.sha256(text.encode("utf-8")).hexdigest()):
        raise ValueError("invalid reply presentation version or text fingerprint")
    for key in ("citation_spans", "hidden_ranges"):
        ranges = value.get(key)
        if not isinstance(ranges, list):
            raise ValueError("invalid reply presentation ranges")
        for pair in ranges:
            if (not isinstance(pair, list) or len(pair) != 2
                    or any(type(i) is not int for i in pair)
                    or not 0 <= pair[0] <= pair[1] <= len(text)):
                raise ValueError("reply presentation range outside canonical text")
    tail = value.get("generated_tail_start")
    if tail is not None and (type(tail) is not int or not 0 <= tail <= len(text)):
        raise ValueError("invalid generated source tail range")
    if not isinstance(value.get("display_text"), str):
        raise ValueError("missing frozen reply display text")
