"""quick_judge_detailed structured-result tests (#75-C)."""

from __future__ import annotations

import pytest

from plugins.llm_provider import LLMResponse
from quickquip.llm.service import QuickJudgeResult


class _StubClient:
    def __init__(self, behavior):
        self.behavior = behavior
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        if isinstance(self.behavior, Exception):
            raise self.behavior
        return self.behavior


def _patch_judge_provider(monkeypatch, behavior):
    import quickquip.llm.service as service_module

    stub = _StubClient(behavior)
    monkeypatch.setattr(service_module, "build_provider_client", lambda provider: stub)
    return stub


@pytest.mark.asyncio
async def test_detailed_ok_returns_text_and_usage(llm_service, monkeypatch):
    response = LLMResponse(
        text='{"trigger": true}',
        model="gpt-test",
        finish_reason="stop",
        input_tokens=12,
        output_tokens=8,
    )
    _patch_judge_provider(monkeypatch, response)

    result = await llm_service.quick_judge_detailed("判定一下", max_tokens=64)

    assert result.outcome == "ok"
    assert result.text == '{"trigger": true}'
    assert result.finish_reason == "stop"
    assert result.input_tokens == 12
    assert result.output_tokens == 8
    assert result.error is None
    diag = result.to_diagnostic()
    assert diag["outcome"] == "ok"
    assert diag["provider"] == "openai-main"
    assert diag["model"] == "gpt-test"
    # 诊断字段白名单：不含任何正文/凭据/endpoint
    assert set(diag) == {
        "outcome", "provider", "model", "finish_reason",
        "input_tokens", "output_tokens", "thinking_tokens", "duration_ms",
    }


@pytest.mark.asyncio
async def test_detailed_empty_body_classified(llm_service, monkeypatch):
    _patch_judge_provider(monkeypatch, LLMResponse(text="", model="gpt-test", finish_reason="stop"))
    result = await llm_service.quick_judge_detailed("判定一下")
    assert result.outcome == "empty"


@pytest.mark.asyncio
async def test_detailed_reasoning_budget_exhaustion_is_length(llm_service, monkeypatch):
    """reasoning 耗尽预算：可见正文为空但根因是截断，归 length 而非 empty。"""
    _patch_judge_provider(
        monkeypatch,
        LLMResponse(text="", model="gpt-test", finish_reason="length", output_tokens=64),
    )
    result = await llm_service.quick_judge_detailed("判定一下")
    assert result.outcome == "length"
    assert result.output_tokens == 64


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["length", "MAX_TOKENS", "Length"])
async def test_detailed_truncation_classified(llm_service, monkeypatch, finish_reason):
    _patch_judge_provider(
        monkeypatch,
        LLMResponse(text='{"trig', model="gpt-test", finish_reason=finish_reason),
    )
    result = await llm_service.quick_judge_detailed("判定一下")
    assert result.outcome == "length"
    assert result.finish_reason == finish_reason


@pytest.mark.asyncio
async def test_detailed_provider_error_captured(llm_service, monkeypatch):
    from plugins.llm_provider import LLMProviderError

    error = LLMProviderError("provider down")
    _patch_judge_provider(monkeypatch, error)
    result = await llm_service.quick_judge_detailed("判定一下")
    assert result.outcome == "provider_error"
    assert result.error is error
    assert result.text == ""


@pytest.mark.asyncio
async def test_public_quick_judge_still_raises_provider_error(llm_service, monkeypatch):
    from plugins.llm_provider import LLMProviderError

    _patch_judge_provider(monkeypatch, LLMProviderError("boom"))
    with pytest.raises(LLMProviderError):
        await llm_service.quick_judge("判定一下")


@pytest.mark.asyncio
async def test_public_quick_judge_returns_text_on_ok(llm_service, monkeypatch):
    _patch_judge_provider(
        monkeypatch, LLMResponse(text='{"trigger": false}', model="gpt-test", finish_reason="stop")
    )
    assert await llm_service.quick_judge("判定一下") == '{"trigger": false}'


def test_no_provider_returns_trigger_false_text():
    result = QuickJudgeResult(text='{"trigger": false}', outcome="no_provider", provider_id="", model="")
    assert result.to_diagnostic()["outcome"] == "no_provider"
