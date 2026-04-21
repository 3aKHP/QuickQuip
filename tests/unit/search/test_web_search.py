from __future__ import annotations

import json

import plugins.web_search as web_search_module
from plugins.tavily_search import TavilySearchResponse, TavilySearchResult
from plugins.web_search import (
    SearchResponse,
    SearchResult,
    SearXNGSearchClient,
    TavilySearchClient,
    build_search_client,
    format_search_response,
)


class FakeSearchHTTPResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_format_tavily_search_response():
    reply = format_search_response(
        TavilySearchResponse(
            query="QuickQuip",
            answer="这是一个 QQ 群聊机器人项目。",
            results=[
                TavilySearchResult(
                    title="QuickQuip README",
                    url="https://example.test/quickquip",
                    content="QuickQuip 是一个基于 NoneBot2 的 QQ 群聊机器人。",
                )
            ],
        )
    )
    assert "联网搜索：QuickQuip" in reply
    assert "摘要：这是一个 QQ 群聊机器人项目。" in reply
    assert "https://example.test/quickquip" in reply


class TestBuildSearchClient:
    def test_defaults_to_tavily_without_envs(self, monkeypatch):
        monkeypatch.delenv("SEARCH_BACKEND", raising=False)
        monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)
        assert isinstance(build_search_client(), TavilySearchClient)

    def test_searxng_base_url_implies_searxng(self, monkeypatch):
        monkeypatch.delenv("SEARCH_BACKEND", raising=False)
        monkeypatch.setenv("SEARXNG_BASE_URL", "http://127.0.0.1:8888")
        assert isinstance(build_search_client(), SearXNGSearchClient)

    def test_explicit_tavily_wins_over_searxng_base_url(self, monkeypatch):
        monkeypatch.setenv("SEARCH_BACKEND", "tavily")
        monkeypatch.setenv("SEARXNG_BASE_URL", "http://127.0.0.1:8888")
        assert isinstance(build_search_client(), TavilySearchClient)


async def test_searxng_request_and_parse(monkeypatch):
    captured: list[tuple[str, int]] = []

    def fake_urlopen(http_request, timeout):
        captured.append((http_request.full_url, timeout))
        return FakeSearchHTTPResponse(
            {
                "query": "QuickQuip",
                "results": [
                    {
                        "title": "QuickQuip README",
                        "url": "https://example.test/quickquip",
                        "content": "QuickQuip 是一个基于 NoneBot2 的 QQ 群聊机器人。",
                        "score": 0.9,
                    }
                ],
            }
        )

    monkeypatch.setattr(web_search_module.request, "urlopen", fake_urlopen)

    response = await SearXNGSearchClient(instance_url="http://127.0.0.1:8888").search(
        "QuickQuip", topic="news", max_results=2
    )

    assert captured
    url = captured[0][0]
    assert "format=json" in url
    assert "categories=news" in url
    assert "q=QuickQuip" in url

    assert response == SearchResponse(
        query="QuickQuip",
        answer=None,
        results=[
            SearchResult(
                title="QuickQuip README",
                url="https://example.test/quickquip",
                content="QuickQuip 是一个基于 NoneBot2 的 QQ 群聊机器人。",
                score=0.9,
            )
        ],
        response_time=None,
        request_id=None,
    )
