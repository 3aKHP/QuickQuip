from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from typing import Any
from urllib import error, parse, request


class WebSearchError(RuntimeError):
    pass


class SearXNGSearchError(WebSearchError):
    pass


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    content: str
    score: float | None = None


@dataclass(slots=True)
class SearchResponse:
    query: str
    answer: str | None
    results: list[SearchResult]
    response_time: float | None = None
    request_id: str | None = None


class SearXNGSearchClient:
    def __init__(
        self,
        base_url_env: str = "SEARXNG_BASE_URL",
        timeout_seconds: float = 30.0,
        instance_url: str | None = None,
    ):
        self.base_url_env = base_url_env
        self.timeout_seconds = timeout_seconds
        self.instance_url = instance_url

    def _get_base_url(self) -> str:
        base_url = (self.instance_url or os.getenv(self.base_url_env, "")).strip()
        if not base_url:
            raise SearXNGSearchError(f"环境变量 {self.base_url_env} 未设置，无法调用 SearXNG 搜索")
        return base_url.rstrip("/")

    def _build_params(self, query: str, topic: str, max_results: int) -> dict[str, str | int]:
        safe_search = os.getenv("SEARXNG_SAFE_SEARCH", "0").strip()
        if safe_search not in {"0", "1", "2"}:
            safe_search = "0"
        params: dict[str, str | int] = {
            "q": query,
            "format": "json",
            "pageno": 1,
            "language": os.getenv("SEARXNG_LANGUAGE", "").strip() or "all",
            "safesearch": safe_search,
            "max_results": max(1, min(int(max_results), 10)),
        }
        if topic.strip().lower() == "news":
            params["categories"] = "news"
        return params

    async def search(
        self,
        query: str,
        *,
        topic: str = "general",
        max_results: int = 5,
        search_depth: str = "basic",
        include_answer: bool = True,
    ) -> SearchResponse:
        _ = search_depth, include_answer
        normalized_query = query.strip()
        if not normalized_query:
            raise SearXNGSearchError("搜索词不能为空")

        params = self._build_params(normalized_query, topic, max_results)
        search_url = f"{self._get_base_url()}/search?{parse.urlencode(params)}"
        http_request = request.Request(
            url=search_url,
            headers={"Accept": "application/json"},
            method="GET",
        )

        def _send() -> dict[str, Any]:
            try:
                with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw)
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                hint = ""
                if exc.code == 403:
                    hint = "，请确认 SearXNG 已在 search.formats 中启用 json"
                raise SearXNGSearchError(f"HTTP {exc.code}{hint} {detail[:240]}") from exc
            except error.URLError as exc:
                raise SearXNGSearchError(f"网络错误：{exc.reason}") from exc

        data = await asyncio.to_thread(_send)
        results = [
            SearchResult(
                title=str(item.get("title", "")).strip(),
                url=str(item.get("url", "")).strip(),
                content=str(item.get("content", "")).strip(),
                score=float(item["score"]) if item.get("score") is not None else None,
            )
            for item in data.get("results", [])
            if isinstance(item, dict)
        ]
        return SearchResponse(
            query=str(data.get("query", normalized_query)),
            answer=(str(data.get("answer", "")).strip() or None),
            results=results,
            response_time=None,
            request_id=None,
        )


def format_search_response(
    response: SearchResponse,
    *,
    include_answer: bool = True,
    max_results: int = 3,
) -> str:
    lines = [f"联网搜索：{response.query}"]
    if include_answer and response.answer:
        lines.append(f"摘要：{response.answer}")

    if not response.results:
        lines.append("没有找到可用结果")
        return "\n".join(lines)

    lines.append("结果：")
    for index, item in enumerate(response.results[:max_results], 1):
        lines.append(f"{index}. {item.title or item.url}")
        lines.append(item.url)
        if item.content:
            lines.append(item.content[:180])
    return "\n".join(lines)
