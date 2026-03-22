from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from typing import Any
from urllib import error, request


TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class TavilySearchError(RuntimeError):
    pass


@dataclass(slots=True)
class TavilySearchResult:
    title: str
    url: str
    content: str
    score: float | None = None


@dataclass(slots=True)
class TavilySearchResponse:
    query: str
    answer: str | None
    results: list[TavilySearchResult]
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
    ) -> TavilySearchResponse:
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
            TavilySearchResult(
                title=str(item.get("title", "")).strip(),
                url=str(item.get("url", "")).strip(),
                content=str(item.get("content", "")).strip(),
                score=float(item["score"]) if item.get("score") is not None else None,
            )
            for item in data.get("results", [])
        ]
        return TavilySearchResponse(
            query=str(data.get("query", normalized_query)),
            answer=(str(data.get("answer", "")).strip() or None),
            results=results,
            response_time=float(data["response_time"]) if data.get("response_time") is not None else None,
            request_id=str(data.get("request_id", "")).strip() or None,
        )


def format_search_response(
    response: TavilySearchResponse,
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
