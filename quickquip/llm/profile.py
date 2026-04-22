from __future__ import annotations

from dataclasses import replace

from quickquip.llm.config import LLMConfig
from quickquip.llm.provider import LLMProviderError, LLMRequest, build_provider_client
from quickquip.llm.tools import LLMConversationMessage

_TEMPERATURE = 0.9
_MAX_OUTPUT_TOKENS = 300


def _parse_cascade_entry(entry: str, fallback_provider: str, fallback_model: str) -> tuple[str, str]:
    if entry == "@default":
        return fallback_provider, fallback_model
    parts = entry.split("/", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (entry, fallback_model)


async def generate_profile(
    target_name: str,
    message_count: int,
    memories: list[str],
    recent_samples: list[str],
    llm_config: LLMConfig,
    system_prompt: str,
    default_provider_id: str,
    default_model: str,
) -> tuple[str, str]:
    sections = [
        f"请以你的语气，写一段关于群友「{target_name}」的简短人物志（约 100 字）。",
        "风格自然随意，像在群里聊天，不要正式介绍。",
        f"\n群内发言：{message_count} 条",
    ]
    if memories:
        sections.append("\n长期记忆（关于 TA 的已知信息）：\n" + "\n".join(f"- {m}" for m in memories[:8]))
    if recent_samples:
        sections.append("\n近期发言样本：\n" + "\n".join(f"- {s}" for s in recent_samples))

    user_message = LLMConversationMessage(role="user", content="\n".join(sections))
    cascade = llm_config.daily_summary.model_cascade or [f"{default_provider_id}/{default_model}"]
    last_error: LLMProviderError | None = None

    for entry in cascade:
        provider_id, model = _parse_cascade_entry(entry, default_provider_id, default_model)
        provider_config = llm_config.providers.get(provider_id)
        if provider_config is None:
            continue
        try:
            client = build_provider_client(replace(provider_config, stream_enabled=False))
            response = await client.complete(LLMRequest(
                model=model,
                system_prompt=system_prompt,
                messages=[user_message],
                temperature=_TEMPERATURE,
                max_output_tokens=_MAX_OUTPUT_TOKENS,
                tools=[],
                allow_tool_calls=False,
            ))
            if response.text.strip():
                return response.text.strip(), f"{provider_id}/{model}"
        except LLMProviderError as exc:
            last_error = exc

    raise LLMProviderError(f"所有模型均失败：{last_error}")
