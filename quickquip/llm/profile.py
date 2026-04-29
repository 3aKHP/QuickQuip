from __future__ import annotations

from dataclasses import replace

from quickquip.llm.config import LLMConfig
from quickquip.llm.provider import LLMProviderError, LLMRequest, build_provider_client
from quickquip.llm.tools import LLMConversationMessage

_TEMPERATURE = 0.9
_MAX_OUTPUT_TOKENS = 300


async def generate_profile(
    target_name: str,
    message_count: int,
    memories: list[str],
    recent_samples: list[str],
    llm_config: LLMConfig,
    system_prompt: str,
    provider_id: str,
    model: str,
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
    provider_config = llm_config.providers.get(provider_id)
    if provider_config is None:
        raise LLMProviderError(f"Provider 未配置：{provider_id}")
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
    if not response.text.strip():
        raise LLMProviderError("LLM 返回空文本")
    return response.text.strip(), f"{provider_id}/{model}"
