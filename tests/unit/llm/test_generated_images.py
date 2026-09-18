"""模型产出图片收集器：外发通道接入、字节上限、数量上限与限流。"""
from __future__ import annotations

import base64

from quickquip.llm.generated_images import collect_generated_images
from quickquip.llm.provider import LLMGeneratedImage, LLMResponse
from quickquip.llm.tools import (
    LLMInlineImage,
    MAX_OUTBOUND_TOOL_IMAGES,
    ToolExecutionContext,
)


def _context(**overrides) -> ToolExecutionContext:
    fields = {
        "group_id": 10086,
        "user_id": 42,
        "sender_name": "tester",
        "provider_id": "fake",
        "model": "m",
    }
    fields.update(overrides)
    return ToolExecutionContext(**fields)


def _image_response(count: int) -> LLMResponse:
    return LLMResponse(
        text="",
        model="m",
        generated_images=[
            LLMGeneratedImage(
                data=base64.b64encode(f"img-{i}".encode()),
                media_type="image/png",
                source="responses.image_generation",
            )
            for i in range(count)
        ],
    )


def test_collect_appends_all_images_within_limits():
    context = _context()
    appended = collect_generated_images(_image_response(2), context)
    assert appended == 2
    assert [img.source_label for img in context.outbound_images] == [
        "responses.image_generation",
        "responses.image_generation",
    ]
    assert context.outbound_images[0].data == base64.b64encode(b"img-0")


def test_collect_respects_outbound_cap(monkeypatch):
    from quickquip.llm import generated_images

    monkeypatch.setattr(generated_images, "generated_image_allowed", lambda *a, **k: True)
    context = _context()
    context.outbound_images.extend(
        LLMInlineImage(data=b"x", media_type="image/png", source_label="seed")
        for _ in range(MAX_OUTBOUND_TOOL_IMAGES)
    )
    appended = collect_generated_images(_image_response(1), context)
    assert appended == 0
    assert len(context.outbound_images) == MAX_OUTBOUND_TOOL_IMAGES


def test_collect_stops_when_rate_limited(monkeypatch):
    from quickquip.llm import generated_images

    monkeypatch.setattr(generated_images, "generated_image_allowed", lambda *a, **k: False)
    context = _context()
    appended = collect_generated_images(_image_response(3), context)
    assert appended == 0
    assert context.outbound_images == []


def test_collect_noop_without_images():
    context = _context()
    assert collect_generated_images(LLMResponse(text="没图", model="m"), context) == 0
    assert context.outbound_images == []


def test_collect_drops_oversize_bytes(monkeypatch):
    from quickquip.llm import generated_images

    monkeypatch.setattr(generated_images, "generated_image_allowed", lambda *a, **k: True)
    monkeypatch.setattr(
        generated_images, "MAX_OUTPUT_PNG_BYTES", 8, raising=False
    )
    context = _context()
    big = LLMGeneratedImage(
        data=b"x" * 16, media_type="image/png", source="responses.image_generation"
    )
    ok = LLMGeneratedImage(
        data=b"x" * 4, media_type="image/png", source="responses.image_generation"
    )
    response = LLMResponse(text="", model="m", generated_images=[big, ok])
    assert collect_generated_images(response, context) == 1
    assert context.outbound_images[0].data == b"x" * 4
