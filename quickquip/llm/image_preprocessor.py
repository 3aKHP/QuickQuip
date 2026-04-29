from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class ImageDescription:
    """Output of image pre-processing for a single image."""

    source_url: str
    text_description: str
    success: bool
    error: str = ""


class ImagePreprocessor(ABC):
    """Converts image URLs to text descriptions.

    Implementations can use OCR, a multimodal model, or any technique
    to produce text representations of image content.  The preprocessor
    runs BEFORE provider serialization, so the main chat LLM receives
    text descriptions instead of (or in addition to) raw image URLs.

    This enables non-multimodal LLMs to "see" images, and also allows
    multimodal LLMs to benefit from structured pre-analysis.
    """

    @abstractmethod
    async def describe_images(
        self, image_urls: list[str]
    ) -> list[ImageDescription]:
        """Convert a batch of image URLs to text descriptions.

        Returns one ImageDescription per input URL.
        Descriptions are injected into the current scene as additional
        context lines before the LLM sees them.
        """
        ...


class NoOpImagePreprocessor(ImagePreprocessor):
    """Default: returns empty list. Images pass through to the provider as-is."""

    async def describe_images(self, image_urls: list[str]) -> list[ImageDescription]:
        return []
