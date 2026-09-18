"""模型产出图片的收集与投递准备（协议中立）。

`LLMResponse.generated_images`（Responses 内置 image_generation 条目 /
Gemini inlineData parts 提取）在各协议适配器归一后，由工具循环在每轮
响应到达时收进 `ToolExecutionContext.outbound_images`——与 draw_svg 等
工具路径的外发图片同通道、同上限（MAX_OUTBOUND_TOOL_IMAGES）、同
"后续调用失败不丢弃已产出图片"语义。

限流与 generation/svg.py 的 svg_render 同风格自持实例：模型生图是
API 侧成本，防 prompt injection 或模型自发刷图。
"""
from __future__ import annotations

import logging

from quickquip.common.rate_limit import KeyedRateLimiter
from quickquip.llm.provider import LLMResponse
from quickquip.llm.tools import (
    MAX_OUTBOUND_TOOL_IMAGES,
    LLMInlineImage,
    ToolExecutionContext,
)

logger = logging.getLogger(__name__)

# 与 svg_render 对齐（全局 10 次/分钟、单用户 2 次/分钟）：两条画图路径
# 在产品层面平权，限额同风格。仅在事件循环线程调用（限流器非线程安全）。
_NATIVE_IMAGE_RATE_LIMITER = KeyedRateLimiter(
    {"native_image": {"global_limit": 10, "user_limit": 2, "scope": "global", "window": 60}}
)


def native_image_allowed(user_id: int | str, group_id: int | str | None = None) -> bool:
    """模型生图限流入口（供测试与观测复用）。"""
    return _NATIVE_IMAGE_RATE_LIMITER.allow(
        "native_image", user_id, group_id=group_id
    )


def collect_native_images(response: LLMResponse, context: ToolExecutionContext) -> int:
    """响应到达点收图：越限/超上限丢弃并留痕，返回实际收进数量。"""
    if not response.generated_images:
        return 0
    appended = 0
    for image in response.generated_images:
        if len(context.outbound_images) >= MAX_OUTBOUND_TOOL_IMAGES:
            logger.warning(
                "native model images dropped (outbound cap %d): provider=%s model=%s",
                MAX_OUTBOUND_TOOL_IMAGES,
                context.provider_id,
                context.model,
            )
            break
        if not native_image_allowed(context.user_id, context.group_id):
            logger.warning(
                "native model image rate-limited: provider=%s model=%s user=%s",
                context.provider_id,
                context.model,
                context.user_id,
            )
            break
        context.outbound_images.append(
            LLMInlineImage(
                data=image.data,
                media_type=image.media_type,
                source_label=image.source,
            )
        )
        appended += 1
    return appended
