"""Anthropic Messages hosted web_search tool declaration and report extraction."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from quickquip.llm.provider.base import LLMWebSearchReport, LLMWebSearchSource

CLAUDE_WEB_SEARCH_TOOL_TYPE = "web_search_20250305"
CLAUDE_WEB_SEARCH_TOOL_NAME = "web_search"
CLAUDE_WEB_SEARCH_MAX_USES = 5


def build_claude_web_search_tool(
    max_uses: int = CLAUDE_WEB_SEARCH_MAX_USES,
) -> dict[str, Any]:
    """Build the Anthropic server-managed web_search tool declaration."""
    return {
        "type": CLAUDE_WEB_SEARCH_TOOL_TYPE,
        "name": CLAUDE_WEB_SEARCH_TOOL_NAME,
        "max_uses": max_uses,
    }


def _valid_http_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    url = value.strip()
    if not url:
        return ""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    return url if parsed.scheme in {"http", "https"} and parsed.hostname else ""


def extract_claude_web_search_report(
    content_blocks: Any,
    usage: Any = None,
) -> LLMWebSearchReport | None:
    """Extract queries, cited/result sources, and compact metadata from Claude content.

    Citations (``web_search_result_location``) are prioritized ahead of uncited
    ``web_search_tool_result`` entries. Opaque ``encrypted_content`` payloads are
    intentionally omitted from ``raw_metadata``.
    """
    if not isinstance(content_blocks, list):
        return None

    queries: list[str] = []
    cited_sources: dict[str, LLMWebSearchSource] = {}
    result_sources: dict[str, LLMWebSearchSource] = {}
    calls_meta: list[dict[str, Any]] = []
    citations_meta: list[dict[str, Any]] = []
    found = False

    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")

        if btype == "server_tool_use" and block.get("name") == CLAUDE_WEB_SEARCH_TOOL_NAME:
            found = True
            tool_input = block.get("input")
            query = ""
            if isinstance(tool_input, dict):
                raw_query = tool_input.get("query")
                if isinstance(raw_query, str):
                    query = raw_query.strip()
            if query and query not in queries:
                queries.append(query)
            call_entry: dict[str, Any] = {"name": CLAUDE_WEB_SEARCH_TOOL_NAME}
            if isinstance(block.get("id"), str) and block["id"]:
                call_entry["id"] = block["id"]
            if query:
                call_entry["query"] = query
            calls_meta.append(call_entry)

        elif btype == "web_search_tool_result":
            found = True
            items = block.get("content")
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict) or item.get("type") != "web_search_result":
                        continue
                    url = _valid_http_url(item.get("url"))
                    if not url:
                        continue
                    title = str(item.get("title") or "").strip()
                    result_sources.setdefault(url, LLMWebSearchSource(title=title, url=url))

        elif btype == "text":
            raw_citations = block.get("citations")
            if not isinstance(raw_citations, list):
                continue
            for citation in raw_citations:
                if (
                    not isinstance(citation, dict)
                    or citation.get("type") != "web_search_result_location"
                ):
                    continue
                url = _valid_http_url(citation.get("url"))
                if not url:
                    continue
                found = True
                title = str(citation.get("title") or "").strip()
                existing = cited_sources.get(url)
                if existing is None or (not existing.title and title):
                    cited_sources[url] = LLMWebSearchSource(title=title, url=url)
                cit_entry: dict[str, Any] = {"type": "web_search_result_location", "url": url}
                if title:
                    cit_entry["title"] = title
                citations_meta.append(cit_entry)

    if not found:
        return None

    ordered_sources: list[LLMWebSearchSource] = []
    seen_urls: set[str] = set()
    for url, source in cited_sources.items():
        if not source.title and url in result_sources and result_sources[url].title:
            source = LLMWebSearchSource(title=result_sources[url].title, url=url)
        ordered_sources.append(source)
        seen_urls.add(url)
    for url, source in result_sources.items():
        if url not in seen_urls:
            ordered_sources.append(source)
            seen_urls.add(url)

    metadata: dict[str, Any] = {
        "calls": calls_meta,
        "citations": citations_meta,
    }
    if isinstance(usage, dict) and isinstance(usage.get("server_tool_use"), dict):
        metadata["server_tool_use"] = dict(usage["server_tool_use"])

    return LLMWebSearchReport(
        queries=queries,
        sources=ordered_sources,
        link_urls=True,
        raw_metadata=metadata,
    )
