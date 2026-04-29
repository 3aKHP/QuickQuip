from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging

from quickquip.llm.tools import LLMConversationMessage
from quickquip.llm.provider import LLMRequest, LLMProviderError

logger = logging.getLogger(__name__)

# ── public types ──────────────────────────────────────────────────────


@dataclass(slots=True)
class ImageDescription:
    """Output of image pre-processing for a single image."""

    source_url: str
    text_description: str
    success: bool
    error: str = ""


class ImagePreprocessor:
    """Converts image URLs to text descriptions.

    Implementations can use OCR, a multimodal model, or any technique
    to produce text representations of image content.  The preprocessor
    runs BEFORE provider serialization, so the main chat LLM receives
    text descriptions instead of (or in addition to) raw image URLs.

    This enables non-multimodal LLMs to "see" images, and also allows
    multimodal LLMs to benefit from structured pre-analysis.
    """

    async def describe_images(
        self, image_urls: list[str]
    ) -> list[ImageDescription]:
        raise NotImplementedError


class NoOpImagePreprocessor(ImagePreprocessor):
    """Default: returns empty list. Images pass through to the provider as-is."""

    async def describe_images(self, image_urls: list[str]) -> list[ImageDescription]:
        return []


# ── default vision prompt ────────────────────────────────────────────

DEFAULT_VISION_PROMPT = (
    "请用简洁的中文描述这张图片的内容，聚焦在群友最可能关心的信息上："
    "文字内容、人物/角色、动作、场景、关键物体、数据表格或图表信息。"
    "不要添加评论或猜测，只描述你看到的内容。"
    "控制在三句话以内。"
)


# ── VisionImagePreprocessor ──────────────────────────────────────────


class VisionImagePreprocessor(ImagePreprocessor):
    """Describe images using an existing vision-capable provider.

    Reuses ``BaseProviderClient`` for image download, base64 encoding,
    protocol adaptation and API calling — no new HTTP logic.

    Each image gets its own request for a focused description.  Up to
    *max_concurrency* images are processed in parallel.
    """

    def __init__(
        self,
        *,
        provider_client,
        model: str,
        max_tokens: int = 300,
        temperature: float = 0.3,
        prompt: str = "",
        max_concurrency: int = 3,
    ):
        self._client = provider_client
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._prompt = prompt.strip() or DEFAULT_VISION_PROMPT
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def describe_images(self, image_urls: list[str]) -> list[ImageDescription]:
        if not image_urls:
            return []

        async def _describe_one(url: str) -> ImageDescription:
            async with self._semaphore:
                return await self._describe_single(url)

        tasks = [_describe_one(url) for url in image_urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        descriptions: list[ImageDescription] = []
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                descriptions.append(ImageDescription(
                    source_url=image_urls[i],
                    text_description="",
                    success=False,
                    error=str(result),
                ))
            else:
                descriptions.append(result)
        return descriptions

    async def _describe_single(self, image_url: str) -> ImageDescription:
        try:
            request = LLMRequest(
                model=self._model,
                system_prompt=self._prompt,
                messages=[
                    LLMConversationMessage(
                        role="user",
                        content="请描述这张图片。",
                        image_urls=[image_url],
                    )
                ],
                temperature=self._temperature,
                max_output_tokens=self._max_tokens,
            )
            response = await self._client.complete(request)
            text = response.text.strip()
            if not text:
                return ImageDescription(
                    source_url=image_url,
                    text_description="",
                    success=False,
                    error="视觉模型返回了空内容",
                )
            return ImageDescription(
                source_url=image_url,
                text_description=text,
                success=True,
            )
        except LLMProviderError as exc:
            return ImageDescription(
                source_url=image_url,
                text_description="",
                success=False,
                error=str(exc),
            )
        except Exception as exc:
            logger.exception("Unexpected error describing image %s", image_url)
            return ImageDescription(
                source_url=image_url,
                text_description="",
                success=False,
                error=str(exc),
            )
