"""VisionImagePreprocessor unit tests.
"""
from __future__ import annotations

import pytest

from quickquip.llm.image_preprocessor import (
    DEFAULT_VISION_PROMPT,
    VisionImagePreprocessor,
)
from quickquip.llm.provider import LLMRequest, LLMResponse, LLMProviderError


# ── stub vision provider client ───────────────────────────────────────

class _StubVisionProvider:
    def __init__(self, replies: list[str] | None = None, *, raise_error: bool = False):
        self.requests: list[LLMRequest] = []
        self._replies = list(replies or [])
        self._raise_error = raise_error

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self._raise_error:
            raise LLMProviderError("stub error")
        text = self._replies.pop(0) if self._replies else "一只猫。"
        return LLMResponse(text=text, model=request.model)


# ── tests ─────────────────────────────────────────────────────────────


def test_constructor_defaults():
    v = VisionImagePreprocessor(
        provider_client=_StubVisionProvider(),
        model="gpt-4o",
    )
    assert v._model == "gpt-4o"
    assert v._max_tokens == 300
    assert v._temperature == 0.3
    assert v._prompt == DEFAULT_VISION_PROMPT


def test_constructor_custom_prompt():
    v = VisionImagePreprocessor(
        provider_client=_StubVisionProvider(),
        model="gpt-4o",
        prompt="自定义 prompt。",
    )
    assert v._prompt == "自定义 prompt。"


@pytest.mark.asyncio
async def test_describe_images_empty_returns_empty():
    v = VisionImagePreprocessor(provider_client=_StubVisionProvider(), model="gpt-4o")
    result = await v.describe_images([])
    assert result == []


@pytest.mark.asyncio
async def test_describe_single_image():
    stub = _StubVisionProvider(replies=["一只橘猫坐在窗台上。"])
    v = VisionImagePreprocessor(provider_client=stub, model="gpt-4o")
    result = await v.describe_images(["https://example.test/cat.png"])

    assert len(result) == 1
    assert result[0].success is True
    assert result[0].source_url == "https://example.test/cat.png"
    assert result[0].text_description == "一只橘猫坐在窗台上。"
    assert stub.requests[0].messages[0].image_urls == ["https://example.test/cat.png"]


@pytest.mark.asyncio
async def test_describe_multiple_images_parallel():
    stub = _StubVisionProvider(replies=["图1", "图2", "图3"])
    v = VisionImagePreprocessor(provider_client=stub, model="gpt-4o", max_concurrency=3)
    result = await v.describe_images([
        "https://example.test/1.png",
        "https://example.test/2.png",
        "https://example.test/3.png",
    ])

    assert len(result) == 3
    assert all(r.success for r in result)
    assert [r.text_description for r in result] == ["图1", "图2", "图3"]
    assert len(stub.requests) == 3


@pytest.mark.asyncio
async def test_describe_provider_error_returns_failure():
    stub = _StubVisionProvider(raise_error=True)
    v = VisionImagePreprocessor(provider_client=stub, model="gpt-4o")
    result = await v.describe_images(["https://example.test/fail.png"])

    assert len(result) == 1
    assert result[0].success is False
    assert result[0].text_description == ""
    assert "stub error" in result[0].error


@pytest.mark.asyncio
async def test_describe_empty_response_returns_failure():
    stub = _StubVisionProvider(replies=[""])
    v = VisionImagePreprocessor(provider_client=stub, model="gpt-4o")
    result = await v.describe_images(["https://example.test/empty.png"])

    assert len(result) == 1
    assert result[0].success is False
    assert "空内容" in result[0].error


@pytest.mark.asyncio
async def test_describe_mixed_success_and_failure():
    class _MixedProvider:
        def __init__(self):
            self.call_count = 0

        async def complete(self, request: LLMRequest) -> LLMResponse:
            self.call_count += 1
            if self.call_count == 2:
                raise LLMProviderError("网络错误")
            return LLMResponse(text=f"描述{self.call_count}", model=request.model)

    stub = _MixedProvider()
    v = VisionImagePreprocessor(provider_client=stub, model="gpt-4o", max_concurrency=1)
    result = await v.describe_images([
        "https://example.test/ok.png",
        "https://example.test/fail.png",
        "https://example.test/ok2.png",
    ])

    assert len(result) == 3
    assert result[0].success is True
    assert result[0].text_description == "描述1"
    assert result[1].success is False
    assert result[2].success is True
    assert result[2].text_description == "描述3"
