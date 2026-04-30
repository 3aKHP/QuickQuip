from __future__ import annotations

import pytest

from quickquip.llm.config import LLMConfig, ProviderConfig
from quickquip.llm.profile import PROFILE_MODES, generate_profile
from quickquip.llm.provider import LLMResponse


class _StubClient:
    def __init__(self):
        self.request = None

    async def complete(self, request):
        self.request = request
        return LLMResponse(text="这是一篇足够长的人物志。", model=request.model)


@pytest.mark.asyncio
async def test_generate_profile_uses_long_form_prompt(monkeypatch):
    client = _StubClient()

    def fake_build_provider_client(config):
        assert config.stream_enabled is False
        return client

    monkeypatch.setattr("quickquip.llm.profile.build_provider_client", fake_build_provider_client)
    config = LLMConfig(
        providers={
            "test": ProviderConfig(
                id="test",
                protocol="openai",
                base_url="https://example.test",
                api_key_env="TEST_API_KEY",
                default_model="model-a",
                models=["model-a"],
            )
        }
    )

    text, model_label = await generate_profile(
        target_name="Alice",
        message_count=123,
        memories=["喜欢研究工具链"],
        recent_samples=["第一条发言", "第二条发言"],
        llm_config=config,
        system_prompt="保持本群口吻",
        provider_id="test",
        model="model-a",
    )

    assert text == "这是一篇足够长的人物志。"
    assert model_label == "test/model-a"
    assert client.request is not None
    assert client.request.max_output_tokens == PROFILE_MODES["middle"].max_output_tokens
    assert client.request.temperature == 0.9
    assert client.request.system_prompt == "保持本群口吻"
    prompt = client.request.messages[0].content
    assert "目标长度约 1600 字" in prompt
    assert "写成有起伏的小作文" in prompt
    assert "近期发言样本（按时间顺序节选）" in prompt
    assert "第一条发言" in prompt


@pytest.mark.asyncio
async def test_generate_profile_short_uses_legacy_scale(monkeypatch):
    client = _StubClient()
    monkeypatch.setattr("quickquip.llm.profile.build_provider_client", lambda config: client)
    config = LLMConfig(
        providers={
            "test": ProviderConfig(
                id="test",
                protocol="openai",
                base_url="https://example.test",
                api_key_env="TEST_API_KEY",
                default_model="model-a",
                models=["model-a"],
            )
        }
    )

    await generate_profile(
        target_name="Alice",
        message_count=123,
        memories=[],
        recent_samples=["发言"],
        llm_config=config,
        system_prompt="",
        provider_id="test",
        model="model-a",
        profile_mode=PROFILE_MODES["short"],
    )

    prompt = client.request.messages[0].content
    assert client.request.max_output_tokens == 300
    assert "简短人物志" in prompt
    assert "目标长度约 100 字" in prompt


@pytest.mark.asyncio
async def test_generate_profile_full_fits_samples_under_input_budget(monkeypatch):
    client = _StubClient()
    monkeypatch.setattr("quickquip.llm.profile.build_provider_client", lambda config: client)
    config = LLMConfig(
        providers={
            "test": ProviderConfig(
                id="test",
                protocol="openai",
                base_url="https://example.test",
                api_key_env="TEST_API_KEY",
                default_model="model-a",
                models=["model-a"],
            )
        }
    )

    await generate_profile(
        target_name="Alice",
        message_count=123,
        memories=[],
        recent_samples=["旧消息" + "a" * 20, "新消息" + "b" * 20],
        llm_config=config,
        system_prompt="",
        provider_id="test",
        model="model-a",
        profile_mode=PROFILE_MODES["full"],
    )

    prompt = client.request.messages[0].content
    assert client.request.max_output_tokens == 8192
    assert "完整发言记录" in prompt
    assert "旧消息" in prompt
    assert "新消息" in prompt
