"""Search tool loop: the LLM can call search_web multiple rounds and the
service should thread each result back into the next request's context.
"""
from __future__ import annotations

import quickquip.llm.service_parts.tools as llm_tools_module
from plugins.web_search import SearchResponse, SearchResult

from tests.fixtures.provider_stubs import StubSearchOnlyProviderClient


class FakeToolSearchClient:
    async def search(self, query, *, topic="general", max_results=5):
        assert query == "QuickQuip"
        assert topic == "general"
        assert max_results == 5
        return SearchResponse(
            query=query,
            answer="这是一个 QQ 群聊机器人项目。",
            results=[
                SearchResult(
                    title="QuickQuip README",
                    url="https://example.test/quickquip",
                    content="QuickQuip 是一个基于 NoneBot2 的 QQ 群聊机器人。",
                )
            ],
        )


def _fake_searxng_client(*args, **kwargs):
    return FakeToolSearchClient()


async def test_search_web_tool_loop(llm_service, monkeypatch, patch_provider_builder):
    stub = StubSearchOnlyProviderClient()
    patch_provider_builder(lambda provider: stub)
    monkeypatch.setattr(llm_tools_module, "SearXNGSearchClient", _fake_searxng_client)
    monkeypatch.setenv("SEARXNG_BASE_URL", "http://127.0.0.1:8888")

    result = await llm_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="QuickQuip 是什么？",
        recent_messages=[],
    )

    assert result["reply"] == "QuickQuip 是一个 QQ 群聊机器人项目。"
    # StubSearchOnly calls search 4 times, then final answer on round 5
    assert len(stub.requests) == 5
    assert "当前联网后端：SearXNG。" in stub.requests[0].system_prompt
    assert "可以继续多次调用 search_web 细化检索" in stub.requests[0].system_prompt
