from __future__ import annotations

from quickquip.common.sensitive_filter import (
    DEFAULT_BLOCK_REPLY,
    DEFAULT_OUTPUT_FALLBACK,
    SensitiveFilter,
)
from quickquip.llm.image_preprocessor import ImageDescription
from quickquip.llm.provider import LLMResponse
from tests.fixtures.provider_stubs import StubProviderClient


def _sensitive_filter(tmp_path, section: str, word: str = "blocked") -> SensitiveFilter:
    path = tmp_path / f"sensitive-{section}.toml"
    path.write_text(
        f'[{section}.test]\nwords = ["{word}"]\n',
        encoding="utf-8",
    )
    return SensitiveFilter.from_toml(path)


async def test_voice_transcript_block_stops_main_provider(
    llm_service,
    patch_provider_builder,
    monkeypatch,
    tmp_path,
):
    sensitive = _sensitive_filter(tmp_path, "block")
    monkeypatch.setattr("quickquip.llm.service._get_sensitive_filter", lambda: sensitive)
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    result = await llm_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="safe prompt",
        voice_text="blocked transcript",
        recent_messages=[],
    )

    assert result["reply"] == DEFAULT_BLOCK_REPLY
    assert stub.last_request is None


async def test_defectify_blocked_input_stops_provider(
    llm_service,
    patch_provider_builder,
    monkeypatch,
    tmp_path,
):
    sensitive = _sensitive_filter(tmp_path, "block")
    monkeypatch.setattr("quickquip.llm.service._get_sensitive_filter", lambda: sensitive)
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    result = await llm_service.generate_defectify_reply(
        chat_id=1001,
        chat_type="group",
        user_id=2002,
        sender_name="测试用户",
        prompt="safe prompt",
        quoted_text="blocked quote",
    )

    assert result["reply"] == DEFAULT_BLOCK_REPLY
    assert result["llm_used"] is False
    assert stub.last_request is None


async def test_defectify_blocked_output_uses_fallback(
    llm_service,
    patch_provider_builder,
    monkeypatch,
    tmp_path,
):
    sensitive = _sensitive_filter(tmp_path, "block")
    monkeypatch.setattr("quickquip.llm.service._get_sensitive_filter", lambda: sensitive)

    class _BlockedOutputClient:
        def __init__(self):
            self.last_request = None

        async def complete(self, request):
            self.last_request = request
            return LLMResponse(text="blocked output", model=request.model)

    client = _BlockedOutputClient()
    patch_provider_builder(lambda provider: client)

    result = await llm_service.generate_defectify_reply(
        chat_id=1001,
        chat_type="group",
        user_id=2002,
        sender_name="测试用户",
        prompt="safe prompt",
    )

    assert client.last_request is not None
    assert result["reply"] == DEFAULT_OUTPUT_FALLBACK
    assert result["llm_used"] is True


async def test_defectify_unloaded_filter_keeps_existing_behavior(
    llm_service,
    patch_provider_builder,
    monkeypatch,
):
    monkeypatch.setattr(
        "quickquip.llm.service._get_sensitive_filter",
        SensitiveFilter.empty,
    )
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    result = await llm_service.generate_defectify_reply(
        chat_id=1001,
        chat_type="group",
        user_id=2002,
        sender_name="测试用户",
        prompt="safe prompt",
    )

    assert stub.last_request is not None
    assert result["reply"].startswith("stub::gpt-test::")


async def test_blocked_image_description_stops_main_provider(
    llm_service,
    patch_provider_builder,
    monkeypatch,
    tmp_path,
):
    sensitive = _sensitive_filter(tmp_path, "block")
    monkeypatch.setattr("quickquip.llm.service._get_sensitive_filter", lambda: sensitive)
    provider = llm_service.config.providers["openai-main"]
    provider.non_vision_models.append("gpt-test")

    class _BlockedDescriptionPreprocessor:
        async def describe_images(self, image_urls):
            return [
                ImageDescription(
                    source_url=url,
                    text_description="blocked image description",
                    success=True,
                )
                for url in image_urls
            ]

    llm_service.image_preprocessor = _BlockedDescriptionPreprocessor()
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    result = await llm_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="safe prompt",
        image_urls=["https://example.test/image.png"],
        recent_messages=[],
    )

    assert result["reply"] == DEFAULT_BLOCK_REPLY
    assert result["llm_used"] is True
    assert stub.last_request is None


async def test_soft_image_description_continues_to_main_provider(
    llm_service,
    patch_provider_builder,
    monkeypatch,
    tmp_path,
):
    sensitive = _sensitive_filter(tmp_path, "soft")
    monkeypatch.setattr("quickquip.llm.service._get_sensitive_filter", lambda: sensitive)
    provider = llm_service.config.providers["openai-main"]
    provider.non_vision_models.append("gpt-test")

    class _SoftDescriptionPreprocessor:
        async def describe_images(self, image_urls):
            return [
                ImageDescription(
                    source_url=url,
                    text_description="blocked image description",
                    success=True,
                )
                for url in image_urls
            ]

    llm_service.image_preprocessor = _SoftDescriptionPreprocessor()
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    result = await llm_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="safe prompt",
        image_urls=["https://example.test/image.png"],
        recent_messages=[],
    )

    assert result["reply"].startswith("stub::gpt-test::")
    assert stub.last_request is not None
    assert any(
        "blocked image description" in message.content
        for message in stub.last_request.messages
    )
