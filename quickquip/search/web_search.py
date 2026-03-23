from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from typing import Any
from urllib import error, parse, request


TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class WebSearchError(RuntimeError):
    pass


class TavilySearchError(WebSearchError):
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


class TavilySearchClient:
    def __init__(self, api_key_env: str = "TAVILY_API_KEY", timeout_seconds: float = 30.0):
        self.api_key_env = api_key_env
        self.timeout_seconds = timeout_seconds

    def _get_api_key(self) -> str:
        api_key = os.getenv(self.api_key_env, "").strip()
        if not api_key:
            raise TavilySearchError(f"环境变量 {self.api_key_env} 未设置，无法调用 Tavily 搜索")
        return api_key

    async def search(
        self,
        query: str,
        *,
        topic: str = "general",
        max_results: int = 5,
        search_depth: str = "basic",
        include_answer: bool = True,
    ) -> SearchResponse:
        normalized_query = query.strip()
        if not normalized_query:
            raise TavilySearchError("搜索词不能为空")

        payload = {
            "query": normalized_query,
            "topic": topic,
            "max_results": max(1, min(int(max_results), 10)),
            "search_depth": search_depth,
            "include_answer": include_answer,
            "include_raw_content": False,
            "include_images": False,
        }
        headers = {
            "Authorization": f"Bearer {self._get_api_key()}",
            "Content-Type": "application/json",
        }
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            url=TAVILY_SEARCH_URL,
            data=body,
            headers=headers,
            method="POST",
        )

        def _send() -> dict[str, Any]:
            try:
                with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw)
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise TavilySearchError(f"HTTP {exc.code} {detail[:240]}") from exc
            except error.URLError as exc:
                raise TavilySearchError(f"网络错误：{exc.reason}") from exc

        data = await asyncio.to_thread(_send)
        results = [
            SearchResult(
                title=str(item.get("title", "")).strip(),
                url=str(item.get("url", "")).strip(),
                content=str(item.get("content", "")).strip(),
                score=float(item["score"]) if item.get("score") is not None else None,
            )
            for item in data.get("results", [])
        ]
        return SearchResponse(
            query=str(data.get("query", normalized_query)),
            answer=(str(data.get("answer", "")).strip() or None),
            results=results,
            response_time=float(data["response_time"]) if data.get("response_time") is not None else None,
            request_id=str(data.get("request_id", "")).strip() or None,
        )


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


def get_search_backend_name(search_backend_env: str = "SEARCH_BACKEND") -> str:
    explicit = os.getenv(search_backend_env, "").strip().lower()
    if explicit and explicit != "auto":
        return explicit
    if os.getenv("SEARXNG_BASE_URL", "").strip():
        return "searxng"
    return "tavily"


def build_search_client(search_backend_env: str = "SEARCH_BACKEND"):
    backend = get_search_backend_name(search_backend_env=search_backend_env)
    if backend == "tavily":
        return TavilySearchClient()
    if backend == "searxng":
        return SearXNGSearchClient()
    raise WebSearchError(f"未知搜索后端：{backend}")


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
