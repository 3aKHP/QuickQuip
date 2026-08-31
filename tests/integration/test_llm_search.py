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


# ---------------------------------------------------------------------------
# gemini builtin_search（google_search grounding）端到端
# ---------------------------------------------------------------------------

def _builtin_search_config(tool_calling_enabled: bool = True) -> str:
    import textwrap

    return textwrap.dedent(
        f"""
        [runtime]
        enabled = true
        default_provider = "gemini-main"
        default_persona = "default"
        tool_calling_enabled = {str(tool_calling_enabled).lower()}

        [triggers.auto_search]
        enabled = true

        [tools]
        enabled = []

        [[personas]]
        id = "default"
        display_name = "默认人格"
        system_prompt = "你是测试人格。"

        [[providers]]
        id = "gemini-main"
        protocol = "gemini"
        base_url = "https://example.test/v1beta"
        api_key_env = "GEMINI_KEY"
        default_model = "gemini-x"
        models = ["gemini-x"]
        builtin_search = true
        """
    ).strip()


def _grounding_response_data() -> dict:
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {"parts": [{"text": "QuickQuip 是一个 QQ 群聊机器人项目。"}]},
                "groundingMetadata": {
                    "webSearchQueries": ["QuickQuip 是什么"],
                    "groundingChunks": [
                        {"web": {"uri": "https://example.test/quickquip", "title": "QuickQuip README"}},
                    ],
                },
            }
        ],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
    }


def _build_builtin_service(tmp_path, tool_calling_enabled: bool = True):
    from plugins.llm_runtime import LLMService
    from tests.fixtures.configs import write_llm_config_bundle

    paths = write_llm_config_bundle(
        tmp_path, config_toml=_builtin_search_config(tool_calling_enabled)
    )
    return LLMService(**paths)


async def test_builtin_search_gemini_flow(tmp_path, monkeypatch, patch_provider_builder):
    """声明入载荷、search_web 移除、提示词引导切换、来源块追加的完整链路。"""
    from tests.fixtures.provider_fakes import FakeGeminiClient

    service = _build_builtin_service(tmp_path)
    monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)  # 内置搜索不依赖 SearXNG
    stub_holder: dict = {}

    def _builder(provider):
        stub_holder["client"] = FakeGeminiClient(provider, _grounding_response_data())
        return stub_holder["client"]

    patch_provider_builder(_builder)

    result = await service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="QuickQuip 是什么？",
        recent_messages=[],
    )

    client = stub_holder["client"]
    payload = client.last_payload
    # 1. 声明入载荷：google_search 独立条目 + 客户端工具不含 search_web
    tool_entries = payload["tools"]
    assert {"google_search": {}} in tool_entries
    declarations = tool_entries[0]["functionDeclarations"]
    assert "search_web" not in [item["name"] for item in declarations]
    # 2. 提示词引导切换为 grounding 块，SearXNG 引导被压制
    system_prompt = payload["systemInstruction"]["parts"][0]["text"]
    assert "联网检索说明" in system_prompt
    assert "当前联网后端：SearXNG。" not in system_prompt
    # 3. 回复末尾追加来源块
    assert result["reply"].endswith(
        "来源：\n- QuickQuip README — example.test"
    )


async def test_builtin_search_works_with_tool_calling_disabled(
    tmp_path, monkeypatch, patch_provider_builder
):
    """工具调用整体关闭时，内置搜索声明与服务端检索仍然生效。"""
    from tests.fixtures.provider_fakes import FakeGeminiClient

    service = _build_builtin_service(tmp_path, tool_calling_enabled=False)
    monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)
    stub_holder: dict = {}

    def _builder(provider):
        stub_holder["client"] = FakeGeminiClient(provider, _grounding_response_data())
        return stub_holder["client"]

    patch_provider_builder(_builder)

    result = await service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="QuickQuip 是什么？",
        recent_messages=[],
    )

    client = stub_holder["client"]
    assert client.last_payload["tools"] == [{"google_search": {}}]
    assert "来源：" in result["reply"]
