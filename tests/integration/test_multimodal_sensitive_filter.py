from __future__ import annotations

from quickquip.common.sensitive_filter import (
    DEFAULT_BLOCK_REPLY,
)
from quickquip.llm.image_preprocessor import ImageDescription
from tests.fixtures.provider_stubs import StubProviderClient
from tests.fixtures.sensitive_filter import make_sensitive_filter


async def test_voice_transcript_block_stops_main_provider(
    llm_service,
    patch_provider_builder,
    monkeypatch,
    tmp_path,
):
    sensitive = make_sensitive_filter(tmp_path, "block")
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
    sensitive = make_sensitive_filter(tmp_path, "block")
    monkeypatch.setattr("quickquip.llm.service._get_sensitive_filter", lambda: sensitive)
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    result = await llm_service.generate_defectify_reply(
        chat_id=1001,
        chat_type="group",
        prompt="safe prompt",
        quoted_text="blocked quote",
    )

    assert result["reply"] == DEFAULT_BLOCK_REPLY
    assert result["llm_used"] is False
    assert stub.last_request is None


async def test_blocked_image_description_stops_main_provider(
    llm_service,
    patch_provider_builder,
    monkeypatch,
    tmp_path,
):
    sensitive = make_sensitive_filter(tmp_path, "block")
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
    sensitive = make_sensitive_filter(tmp_path, "soft")
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
