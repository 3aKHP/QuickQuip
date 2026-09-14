"""IR → OpenAI Responses 请求序列化：input items、call_id 记账与档位映射。

移植自 prism-vesicle request.ts 的 HTTP 路径，契约要点：

- ``store: false`` + 每轮全量回放：请求不携带 ``previous_response_id``，
  历史由 input items 数组完整表达（与 QuickQuip 历史投影/冻结契约对齐）。
- ``instructions`` 折叠 system；工具结果 ``function_call_output`` 按
  call_id 关联；工具产出图片不能挂 output item，完整工具批次结束后经
  合成 user 消息统一 flush（对齐 openai.py 现做法）。
- call_id 记账 fail-closed：未声明先输出/重复声明/重复应答/声明无应答
  均抛错——部分执行的批次必然破坏协议配对，超额批次由工具循环整批
  拒绝（tool_loop.py）保证"全有或全无"。
- 当前循环 assistant 的原生 output items（含 reasoning 密文）按原顺序
  原样回放，同一原生批次只序列化一次；通用字段（content/tool_calls/
  thinking_blocks）此时不再二次投影。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from quickquip.llm.config import ProviderConfig
from quickquip.llm.provider.base import LLMImageInput, LLMProviderError, LLMRequest
from quickquip.llm.provider.openai_responses.profiles import (
    ResponsesProfile,
    resolve_profile,
)
from quickquip.llm.provider.openai_responses.response import validate_output_items

# store:false 常量：手动上下文管理，服务端不留响应态，续接上下文由本端
# input items 完整表达。显式请求 reasoning 密文以兼容目标中转的回传。
STORE = False
INCLUDE_ENCRYPTED_REASONING = ["reasoning.encrypted_content"]

# 六档（low/medium/high/xhigh/max/ultra）→ 各 profile 实际 effort 的映射表，
# 集中一处（1.16 决策 3/4）。max/ultra 超出首批两 profile 的 wire 词表
# （low..xhigh），按降档规则收敛到该 profile 最高档；新 profile 引入时在
# 此补列。thinking_budget 数字口径不适用于本协议（claude/gemini 专属）。
_REASONING_EFFORT_MAP: dict[str, dict[str, str]] = {
    tier: {
        profile_id: ("xhigh" if tier in ("max", "ultra") else tier)
        for profile_id in ("openai-public", "codex-http-relay")
    }
    for tier in ("low", "medium", "high", "xhigh", "max", "ultra")
}

_TOOL_IMAGE_NOTICE = "以下图片来自刚才工具调用，仅用于继续推理。"


def reasoning_control(config: ProviderConfig, profile: ResponsesProfile) -> dict | None:
    """reasoning 档位控制：未配置档位返回 None（不发送字段）。"""
    tier = (config.reasoning_effort or "").strip()
    if not tier:
        return None
    mapped = _REASONING_EFFORT_MAP.get(tier, {}).get(profile.profile_id)
    if mapped is None:
        raise LLMProviderError(
            f"未知的 reasoning 档位：{tier!r}（可用："
            f"{'/'.join(_REASONING_EFFORT_MAP)}）"
        )
    effort = mapped
    if effort not in profile.wire_efforts:  # 降档规则的兜底断言
        raise LLMProviderError(
            f"reasoning 档位映射结果 {effort!r} 不在 profile "
            f"{profile.profile_id} 支持集内"
        )
    return {"effort": effort, "summary": "auto"}


def build_responses_payload(
    request: LLMRequest,
    config: ProviderConfig,
    *,
    stream: bool,
    prepared_images: list[list[LLMImageInput]],
) -> dict[str, Any]:
    profile = resolve_profile(config.responses_profile)
    payload: dict[str, Any] = {
        "model": request.model,
        "input": serialize_input_items(
            request.messages, prepared_images, provider_id=config.id
        ),
        "store": STORE,
        "stream": stream,
        "include": list(INCLUDE_ENCRYPTED_REASONING),
        "temperature": request.temperature,
        "max_output_tokens": request.max_output_tokens,
    }
    if request.system_prompt:
        payload["instructions"] = request.system_prompt
    if request.allow_tool_calls and request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.input_schema,
            }
            for spec in request.tools
        ]
        payload["tool_choice"] = request.tool_choice
        payload["parallel_tool_calls"] = True
    reasoning = reasoning_control(config, profile)
    if reasoning is not None:
        payload["reasoning"] = reasoning
    if profile.service_tier is not None:
        payload["service_tier"] = profile.service_tier
    return payload


def serialize_input_items(
    messages: list,
    prepared_images: list[list[LLMImageInput]],
    *,
    provider_id: str,
) -> list[dict[str, Any]]:
    declared: set[str] = set()
    answered: set[str] = set()
    input_items: list[dict[str, Any]] = []
    # function_call_output 不能携带图片：工具结果图片在完整工具批次结束
    # 后合成一条 user 消息统一 flush（批次中途不 flush，保持配对连续）。
    pending_tool_images: list[LLMImageInput] = []

    def _fail(detail: str) -> LLMProviderError:
        return LLMProviderError(f"[{provider_id}] OpenAI Responses 序列化失败：{detail}")

    def _declare(call_id: Any) -> str:
        if not isinstance(call_id, str) or not call_id:
            raise _fail("function call 缺少 call_id。")
        if call_id in declared:
            raise _fail(f"function call_id {call_id} 被重复声明。")
        declared.add(call_id)
        return call_id

    def _flush_tool_images() -> None:
        nonlocal pending_tool_images
        if not pending_tool_images:
            return
        content: list[dict[str, Any]] = [
            {
                "type": "input_image",
                "image_url": f"data:{item.media_type};base64,{item.data_base64}",
            }
            for item in pending_tool_images
        ]
        content.append({"type": "input_text", "text": _TOOL_IMAGE_NOTICE})
        input_items.append({"role": "user", "content": content})
        pending_tool_images = []

    for message, image_inputs in zip(messages, prepared_images, strict=True):
        if message.role != "tool":
            _flush_tool_images()
        if message.role == "assistant" and message.native_content is not None:
            items = validate_output_items(
                message.native_content, provider_id=provider_id
            )
            for item in items:
                if item.get("type") == "function_call":
                    _declare(item.get("call_id"))
            input_items.extend(deepcopy(item) for item in items)
            continue
        if message.role == "tool":
            call_id = message.tool_call_id
            if not isinstance(call_id, str) or not call_id:
                raise _fail("工具输出缺少 call_id。")
            if call_id not in declared:
                raise _fail(f"function 输出没有前置声明的 call_id {call_id}。")
            if call_id in answered:
                raise _fail(f"call_id {call_id} 被重复应答。")
            answered.add(call_id)
            input_items.append(
                {"type": "function_call_output", "call_id": call_id, "output": message.content}
            )
            pending_tool_images.extend(image_inputs)
            continue
        if message.role == "assistant" and message.tool_calls:
            if message.content:
                input_items.append({"role": "assistant", "content": message.content})
            for call in message.tool_calls:
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": _declare(call.id),
                        "name": call.name,
                        "arguments": call.arguments_json or "{}",
                    }
                )
            continue
        if message.role == "user" and image_inputs:
            content: list[dict[str, Any]] = []
            if message.content:
                content.append({"type": "input_text", "text": message.content})
            content.extend(
                {
                    "type": "input_image",
                    "image_url": f"data:{item.media_type};base64,{item.data_base64}",
                }
                for item in image_inputs
            )
            input_items.append({"role": "user", "content": content})
            continue
        input_items.append({"role": message.role, "content": message.content})

    _flush_tool_images()
    unanswered = declared - answered
    if unanswered:
        first = sorted(unanswered)[0]
        raise _fail(f"function call_id {first} 没有对应结果。")
    return input_items
