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
        and item["status"] in {"in_progress", "searching", "completed", "failed"}
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


def search_report(items: list[dict]) -> LLMWebSearchReport | None:
    queries: list[str] = []
    sources: dict[str, LLMWebSearchSource] = {}
    found = False
    for item in items:
        if item.get("type") == "web_search_call":
            found = True
            action = item["action"]
            if action["type"] == "search":
                queries.extend(q for q in action.get("queries", []) if q not in queries)
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
    return LLMWebSearchReport(queries=queries, sources=list(sources.values())) if found else None


def citations(part: dict) -> list[dict]:
    annotations = part.get("annotations", [])
    if not isinstance(annotations, list):
        return []
    return [a for a in annotations if isinstance(a, dict)
            and a.get("type") == "url_citation" and _url(a.get("url"))]


def cited_text(part: dict) -> str:
    text = str(part.get("text", ""))
    # Citation offsets refer to the original text; replace from right to left.
    replacements = []
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
                replacements.append((start, end, label + f" ({url})"))
    boundary = len(text)
    for start, end, replacement in sorted(replacements, reverse=True):
        if end <= boundary:
            text = text[:start] + replacement + text[end:]
            boundary = start
    # Sources without offsets still need a usable link in the delivered text.
    for annotation in citations(part):
        if annotation["url"] not in text:
            text += "\n" + annotation["url"]
    return text
