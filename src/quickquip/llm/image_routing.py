from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from quickquip.llm.image_preprocessor import (
    MAX_IMAGES_PER_PREPROCESSING_REQUEST,
    ImageDescription,
)
from quickquip.llm.prompting import collect_recent_image_urls


IMAGE_PREPROCESSING_UNAVAILABLE_REPLY = "当前模型无法直接读取图片，且前置图片识别服务不可用。请稍后重试或切换视觉模型。"
IMAGE_PREPROCESSING_FAILED_REPLY = "前置图片识别失败，为避免错误猜测，本次没有调用主模型。请稍后重试或切换视觉模型。"


@dataclass(frozen=True, slots=True)
class ImageCandidate:
    """One image selected for front-model description with a stable source label."""

    url: str
    context_label: str


@dataclass(frozen=True, slots=True)
class ImageRoutingPlan:
    """Bounded image candidates or a user-facing validation failure."""

    candidates: list[ImageCandidate]
    error_reply: str = ""


@dataclass(frozen=True, slots=True)
class ImageDescriptionMatch:
    """Successful labeled descriptions plus image URLs that could not be described."""

    descriptions: list[ImageDescription]
    failed_urls: list[str]


def _append_candidates(
    candidates: list[ImageCandidate],
    seen: set[str],
    urls: list[str],
    source: str,
) -> None:
    for index, raw_url in enumerate(urls, 1):
        url = raw_url.strip()
        if not url or url in seen:
            continue
        seen.add(url)
        candidates.append(ImageCandidate(url=url, context_label=f"{source} {index}"))


def plan_non_vision_images(
    *,
    image_urls: list[str],
    quoted_image_urls: list[str],
    forward_image_urls: list[str],
    recent_messages: Sequence[Mapping[str, object]] | None,
    include_recent_images: bool,
    max_trigger_context_messages: int,
) -> ImageRoutingPlan:
    """Build the bounded image set that a non-vision main model needs described."""
    candidates: list[ImageCandidate] = []
    seen: set[str] = set()
    _append_candidates(candidates, seen, image_urls, "当前消息图片")
    _append_candidates(candidates, seen, quoted_image_urls, "引用消息图片")
    _append_candidates(candidates, seen, forward_image_urls, "转发消息图片")

    if len(candidates) > MAX_IMAGES_PER_PREPROCESSING_REQUEST:
        return ImageRoutingPlan(
            candidates=[],
            error_reply=(
                f"一次最多识别 {MAX_IMAGES_PER_PREPROCESSING_REQUEST} 张图片，请减少图片数量后重试。"
            ),
        )

    if include_recent_images:
        recent_image_urls = collect_recent_image_urls(
            recent_messages,
            max_trigger_context_messages=max_trigger_context_messages,
            max_recent_images=MAX_IMAGES_PER_PREPROCESSING_REQUEST - len(candidates),
        )
        _append_candidates(candidates, seen, recent_image_urls, "近期上下文图片")

    return ImageRoutingPlan(candidates=candidates)


def match_image_descriptions(
    candidates: list[ImageCandidate],
    raw_descriptions: list[ImageDescription],
) -> ImageDescriptionMatch:
    """Match successful descriptions back to their source labels and report gaps."""
    descriptions_by_url = {
        description.source_url: description for description in raw_descriptions
    }
    descriptions: list[ImageDescription] = []
    failed_urls: list[str] = []
    for candidate in candidates:
        description = descriptions_by_url.get(candidate.url)
        if (
            description is None
            or not description.success
            or not description.text_description.strip()
        ):
            failed_urls.append(candidate.url)
            continue
        descriptions.append(replace(description, context_label=candidate.context_label))
    return ImageDescriptionMatch(descriptions=descriptions, failed_urls=failed_urls)
