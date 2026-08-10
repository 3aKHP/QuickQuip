from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging

from quickquip.llm.tools import LLMConversationMessage, LLMInlineImage
from quickquip.llm.provider import LLMRequest, LLMProviderError
from quickquip.llm.usage import usage_scope

logger = logging.getLogger(__name__)

MAX_IMAGES_PER_PREPROCESSING_REQUEST = 5

# ── public types ──────────────────────────────────────────────────────


@dataclass(slots=True)
class ImageDescription:
    """Output of image pre-processing for a single image."""

    source_url: str
    text_description: str
    success: bool
    error: str = ""
    context_label: str = ""


class ImagePreprocessor:
    """Converts image URLs to text descriptions.

    Implementations can use OCR, a multimodal model, or any technique
    to produce text representations of image content.  The preprocessor
    runs BEFORE provider serialization, so the main chat LLM receives
    text descriptions instead of raw image URLs. This enables
    non-multimodal LLMs to "see" images.
    """

    async def describe_images(
        self, image_urls: list[str]
    ) -> list[ImageDescription]:
        raise NotImplementedError

    async def describe_inline_images(
        self, images: list[LLMInlineImage]
    ) -> list[ImageDescription]:
        raise NotImplementedError


class NoOpImagePreprocessor(ImagePreprocessor):
    """Default: returns empty list. Images pass through to the provider as-is."""

    async def describe_images(self, image_urls: list[str]) -> list[ImageDescription]:
        return []

    async def describe_inline_images(self, images: list[LLMInlineImage]) -> list[ImageDescription]:
        return []


# ── default vision prompt ────────────────────────────────────────────

DEFAULT_VISION_PROMPT = (
    "你是一个图片内容转述器。你的任务是对每张图片同时完成文字提取和画面描述，"
    "让没看过图的群友也能完整理解图片信息。\n"
    "\n"
    "请按以下格式输出：\n"
    "\n"
    "【图中文字】\n"
    "逐字提取图片中出现的所有文字，包括标题、正文、标注、水印、聊天记录、"
    "UI 界面文字等。如果没有文字，写「无文字」。\n"
    "\n"
    "【画面描述】\n"
    "描述图片的视觉内容：人物/角色、动作、场景、关键物体、构图关系、"
    "数据图表趋势等。只描述你看到的，不要评论或猜测。\n"
    "\n"
    "如果图片是纯文本截图（聊天记录、公告、文档等），文字提取部分应尽量完整，"
    "画面描述部分可简短说明排版和来源特征。\n"
    "如果图片是照片或插画，画面描述部分应比文字提取更详细。"
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

        with usage_scope("vision"):
            async def _describe_one(url: str) -> ImageDescription:
                async with self._semaphore:
                    return await self._describe_single(url)

            bounded_urls = image_urls[:MAX_IMAGES_PER_PREPROCESSING_REQUEST]
            tasks = [_describe_one(url) for url in bounded_urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            descriptions: list[ImageDescription] = []
            for i, result in enumerate(results):
                if isinstance(result, BaseException):
                    descriptions.append(ImageDescription(
                        source_url=bounded_urls[i],
                        text_description="",
                        success=False,
                        error=str(result),
                    ))
                else:
                    descriptions.append(result)
            return descriptions

    async def describe_inline_images(
        self, images: list[LLMInlineImage]
    ) -> list[ImageDescription]:
        if not images:
            return []

        with usage_scope("vision"):
            async def _describe_one(image: LLMInlineImage) -> ImageDescription:
                async with self._semaphore:
                    return await self._describe_inline_single(image)

            bounded_images = images[:MAX_IMAGES_PER_PREPROCESSING_REQUEST]
            results = await asyncio.gather(
                *[_describe_one(image) for image in bounded_images],
                return_exceptions=True,
            )
            descriptions: list[ImageDescription] = []
            for image, result in zip(bounded_images, results, strict=True):
                if isinstance(result, BaseException):
                    descriptions.append(ImageDescription(
                        source_url=image.source_label,
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

    async def _describe_inline_single(self, image: LLMInlineImage) -> ImageDescription:
        try:
            request = LLMRequest(
                model=self._model,
                system_prompt=self._prompt,
                messages=[
                    LLMConversationMessage(
                        role="user",
                        content="请描述这张图片。",
                        inline_images=[image],
                    )
                ],
                temperature=self._temperature,
                max_output_tokens=self._max_tokens,
            )
            response = await self._client.complete(request)
            text = response.text.strip()
            if not text:
                return ImageDescription(
                    source_url=image.source_label,
                    text_description="",
                    success=False,
                    error="视觉模型返回了空内容",
                )
            return ImageDescription(
                source_url=image.source_label,
                text_description=text,
                success=True,
            )
        except LLMProviderError as exc:
            return ImageDescription(
                source_url=image.source_label,
                text_description="",
                success=False,
                error=str(exc),
            )
        except Exception as exc:
            logger.exception("Unexpected error describing inline image %s", image.source_label)
            return ImageDescription(
                source_url=image.source_label,
                text_description="",
                success=False,
                error=str(exc),
            )
