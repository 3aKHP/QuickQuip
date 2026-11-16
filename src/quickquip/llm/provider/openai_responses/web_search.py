"""Responses hosted search validation and citation projection."""
from __future__ import annotations

from urllib.parse import urlsplit

from quickquip.llm.provider.base import LLMProviderError, LLMWebSearchReport, LLMWebSearchSource

# U+E200 prefixes opaque citation markers in some upstream response fragments.
# Interpret it only inside a url_citation annotation's character range.
CITATION_MARK = "\ue200"


def validate_search_item(item: dict, provider_id: str) -> None:
    action = item.get("action")
    valid = (
        isinstance(item.get("id"), str) and bool(item["id"])
        and isinstance(item.get("status"), str)
        and item["status"] in {"in_progress", "searching", "completed", "failed", "incomplete"}
        and isinstance(action, dict)
        and isinstance(action.get("type"), str)
        and action["type"] in {"search", "open_page", "find_in_page"}
    )
    if valid and action["type"] in {"open_page", "find_in_page"}:
        valid = action.get("url") is None or isinstance(action["url"], str)
        if action["type"] == "find_in_page":
            valid = valid and isinstance(action.get("pattern"), str)
    if valid and action["type"] == "search":
        for key in ("queries", "sources"):
            if key in action and not isinstance(action[key], list):
                valid = False
        if "queries" in action and isinstance(action["queries"], list):
            valid = valid and all(isinstance(q, str) for q in action["queries"])
    if not valid:
        raise LLMProviderError(f"[{provider_id}] Provider 响应包含畸形 web_search_call item。")


def _url(value) -> str:
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in {"http", "https"} and parsed.hostname else ""
    except ValueError:
        return ""


def _action_metadata(action: dict) -> dict:
    result = {key: value for key, value in action.items()
              if key in {"type", "query", "url", "pattern"} and isinstance(value, str)}
    if isinstance(action.get("queries"), list):
        result["queries"] = [q for q in action["queries"] if isinstance(q, str)]
    if isinstance(action.get("sources"), list):
        result["sources"] = [
            {**{"type": "url", "url": source["url"]},
             **({"title": source["title"]} if isinstance(source.get("title"), str) else {})}
            for source in action["sources"]
            if isinstance(source, dict) and _url(source.get("url"))
        ]
    return result


def _citation_metadata(part: dict) -> list[dict]:
    return [
        {key: value for key, value in annotation.items()
         if ((key in {"type", "url", "title"} and isinstance(value, str))
             or (key in {"start_index", "end_index"} and type(value) is int))}
        for annotation in citations(part)
    ]


def search_report(items: list[dict]) -> LLMWebSearchReport | None:
    queries: list[str] = []
    sources: dict[str, LLMWebSearchSource] = {}
    found = False
    for item in items:
        if item.get("type") == "web_search_call":
            found = True
            action = item["action"]
            if action["type"] == "search":
                candidates = ([action["query"]] if isinstance(action.get("query"), str) else [])
                candidates.extend(action.get("queries", []))
                queries.extend(q for q in candidates if q and q not in queries)
            source_items = action.get("sources", []) if action["type"] == "search" else []
            for source in source_items:
                if isinstance(source, dict) and (url := _url(source.get("url"))):
                    sources.setdefault(url, LLMWebSearchSource(title="", url=url))
        if item.get("type") == "message":
            for part in item.get("content", []):
                for annotation in citations(part):
                    found = True
                    url = annotation["url"]
                    sources[url] = LLMWebSearchSource(
                        title=str(annotation.get("title") or ""), url=url,
                    )
    metadata = {
        # Native state (including opaque ciphers) has its own retention/size policy.
        # Keep source/action metadata here without creating a second native copy.
        "calls": [
            {"type": "web_search_call", "action": _action_metadata(item["action"])}
            for item in items if item.get("type") == "web_search_call"
        ],
        "citations": [
            {"item_index": index, "part_index": part_index,
             "annotations": _citation_metadata(part)}
            for index, item in enumerate(items) if item.get("type") == "message"
            for part_index, part in enumerate(item.get("content", [])) if citations(part)
        ],
    }
    return (LLMWebSearchReport(queries=queries, sources=list(sources.values()), link_urls=True,
                              raw_metadata=metadata)
            if found else None)


def citations(part: dict) -> list[dict]:
    annotations = part.get("annotations", [])
    if not isinstance(annotations, list):
        return []
    return [a for a in annotations if isinstance(a, dict)
            and a.get("type") == "url_citation" and _url(a.get("url"))]


def cited_text(part: dict) -> str:
    return cited_text_and_spans(part)[0]


def cited_text_and_spans(
    part: dict, *, opaque_spans: list[tuple[int, int]] | None = None,
) -> tuple[str, list[tuple[int, int]]]:
    text = str(part.get("text", ""))
    # Citation offsets refer to the original text; replace from right to left.
    replacements = []
    spans = []
    markers: list[tuple[int, int]] = []
    for annotation in citations(part):
        start, end = annotation.get("start_index"), annotation.get("end_index")
        if (type(start) is int and type(end) is int and 0 <= start < end <= len(text)):
            fragment = text[start:end]
            url = annotation["url"]
            if url not in fragment:
                label = (
                    str(annotation.get("title") or "来源")
                    if CITATION_MARK in fragment else fragment
                )
                replacements.append((start, end, label + f" ({url})", len(label),
                                     CITATION_MARK in fragment))
            else:
                spans.append((start, end))
    boundary = len(text)
    for start, end, replacement, label_length, opaque_marker in sorted(replacements, reverse=True):
        if end <= boundary:
            text = text[:start] + replacement + text[end:]
            delta = len(replacement) - (end - start)
            spans = [
                (a if a <= start else (a + delta if a >= end else start),
                 b if b <= start else (b + delta if b >= end else start + len(replacement)))
                for a, b in spans
            ]
            markers = [(a + delta if a >= end else a, b + delta if b >= end else b)
                       for a, b in markers]
            # Ordinary annotations may cover scalar facts, code or whole sentences.
            # Only our added URL suffix is presentation syntax in that case.
            spans.append((start + label_length, start + len(replacement)))
            if opaque_marker:
                markers.append((start, start + label_length))
            boundary = start
    # Sources without offsets still need a usable link in the delivered text.
    for annotation in citations(part):
        if annotation["url"] not in text:
            start = len(text)
            text += "\n" + annotation["url"]
            spans.append((start, len(text)))
    if opaque_spans is not None:
        opaque_spans.extend(markers)
    return text, spans
