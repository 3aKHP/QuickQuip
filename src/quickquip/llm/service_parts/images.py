"""当轮图像预处理阶段 mixin（non-VLM 规划、图注转述与敏感词扫描）。

``_preprocess_images_for_model`` 自 ``service.py`` 原样下沉；保持方法形态，
编排器经 ``self.`` 调用——实例级 patch 接缝
（``monkeypatch.setattr(service, "_preprocess_images_for_model", ...)``）
语义不变。敏感词过滤器由编排器以参数传入（解析仍发生在 service 模块
patch 点）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from quickquip.llm.config import ProviderConfig
from quickquip.llm.image_preprocessor import ImageDescription
from quickquip.llm.image_routing import (
    IMAGE_PREPROCESSING_FAILED_REPLY,
    IMAGE_PREPROCESSING_UNAVAILABLE_REPLY,
    match_image_descriptions,
    plan_non_vision_images,
)
from quickquip.llm.prompting import merge_image_urls
from quickquip.llm.reply_chain import reply_result
from quickquip.llm.service_parts.constants import MAX_TRIGGER_CONTEXT_MESSAGES
from quickquip.llm.settings import ResolvedGroupSettings
from quickquip.common.sensitive_filter import (
    DEFAULT_BLOCK_REPLY,
    SensitiveFilter,
    scan_and_log as _scan_sensitive_text,
)

logger = logging.getLogger(__name__)


@dataclass
class ImagePreprocessingOutcome:
    """图像预处理段继续走主生成链路时向调用方回传的状态。"""

    effective_image_urls: list[str]
    request_quoted_image_urls: list[str]
    request_forward_image_urls: list[str]
    image_descriptions: list[ImageDescription]
    is_non_vision: bool


class ImagesMixin:
    """主链的图像预处理阶段：non-VLM 剥离与图注生成。"""

    async def _preprocess_images_for_model(
        self,
        *,
        chat_id: int | str,
        scope_key: str,
        provider: ProviderConfig,
        settings: ResolvedGroupSettings,
        request_image_urls: list[str],
        request_quoted_image_urls: list[str],
        request_forward_image_urls: list[str],
        normalized_image_urls: list[str],
        normalized_quoted_image_urls: list[str],
        normalized_forward_image_urls: list[str],
        recent_messages: list[dict[str, str]] | None,
        include_recent_images: bool,
        sensitive: SensitiveFilter,
    ) -> dict[str, object] | ImagePreprocessingOutcome:
        # ── image preprocessing & non-VLM stripping ──────────────────
        current_model = settings.model or provider.default_model
        is_non_vision = current_model in provider.non_vision_models
        # 转发图片不作为媒体本体附带（媒体本体永不进前缀），仅以文本/图注形式出现
        effective_image_urls = merge_image_urls(request_image_urls, request_quoted_image_urls)

        image_plan = None
        if is_non_vision:
            image_plan = plan_non_vision_images(
                image_urls=request_image_urls,
                quoted_image_urls=request_quoted_image_urls,
                forward_image_urls=request_forward_image_urls,
                recent_messages=recent_messages,
                include_recent_images=include_recent_images,
                max_trigger_context_messages=MAX_TRIGGER_CONTEXT_MESSAGES,
            )
            if image_plan.error_reply:
                return reply_result(image_plan.error_reply, llm_used=False)

        if effective_image_urls:
            # images= 是实际附带数（转发图不附带，不计入）；sources 各分项同理
            # 只列附带来源，避免 total 与分项和对不上误导排查
            sources: list[str] = []
            if normalized_image_urls:
                sources.append(f"直接={len(normalized_image_urls)}")
            if normalized_quoted_image_urls:
                sources.append(f"引用={len(normalized_quoted_image_urls)}")
            logger.info(
                "group=%s model=%s non_vision=%s images=%d (%s)",
                chat_id, current_model, is_non_vision,
                len(effective_image_urls), ", ".join(sources),
            )

        image_descriptions: list[ImageDescription] = []
        ok_count = 0
        if image_plan is not None and image_plan.candidates:
            if self.image_preprocessor is None:
                logger.error(
                    "group=%s model=%s requires image preprocessing but no preprocessor is bound",
                    chat_id,
                    current_model,
                )
                return reply_result(
                    IMAGE_PREPROCESSING_UNAVAILABLE_REPLY,
                    llm_used=False,
                    provider_id=provider.id,
                    model=current_model,
                )

            raw_descriptions = await self.image_preprocessor.describe_images(
                [candidate.url for candidate in image_plan.candidates]
            )
            description_match = match_image_descriptions(
                image_plan.candidates,
                raw_descriptions,
            )
            image_descriptions = description_match.descriptions
            ok_count = len(image_descriptions)
            if description_match.failed_urls:
                logger.warning(
                    "group=%s preprocessor: %d ok, %d failed (%s)",
                    chat_id,
                    ok_count,
                    len(description_match.failed_urls),
                    ", ".join(description_match.failed_urls),
                )
                return reply_result(
                    IMAGE_PREPROCESSING_FAILED_REPLY,
                    llm_used=True,
                    provider_id=self.config.image_preprocessing.provider_id,
                    model=self.config.image_preprocessing.model,
                )
            description_blob = "\n".join(
                item.text_description for item in image_descriptions
                if item.text_description
            )
            description_scan = _scan_sensitive_text(
                description_blob,
                channel="image_description",
                scope=scope_key,
                sensitive_filter=sensitive,
            )
            if description_scan.blocked:
                return reply_result(
                    DEFAULT_BLOCK_REPLY,
                    llm_used=True,
                    provider_id=self.config.image_preprocessing.provider_id,
                    model=self.config.image_preprocessing.model,
                )
            logger.info("group=%s preprocessor: all %d images described", chat_id, ok_count)

        if image_plan is not None and image_plan.candidates:
            stripped_count = len(image_plan.candidates)
            logger.info(
                "group=%s non-VLM strip: replaced %d images with text descriptions",
                chat_id,
                stripped_count,
            )
            effective_image_urls = []
            request_image_urls = []
            request_quoted_image_urls = []
            request_forward_image_urls = []

        # ── end image preprocessing ─────────────────────────────────
        return ImagePreprocessingOutcome(
            effective_image_urls=effective_image_urls,
            request_quoted_image_urls=request_quoted_image_urls,
            request_forward_image_urls=request_forward_image_urls,
            image_descriptions=image_descriptions,
            is_non_vision=is_non_vision,
        )
