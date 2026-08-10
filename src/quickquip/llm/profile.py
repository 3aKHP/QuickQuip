from __future__ import annotations

from dataclasses import dataclass, replace

from quickquip.llm.config import LLMConfig
from quickquip.llm.provider import LLMProviderError, LLMRequest, build_provider_client
from quickquip.llm.tools import LLMConversationMessage
from quickquip.llm.usage import set_usage_scope

_TEMPERATURE = 0.9


@dataclass(frozen=True, slots=True)
class ProfileModeConfig:
    id: str
    label: str
    target_chars: int
    max_output_tokens: int
    memory_limit: int
    sample_limit: int | None
    sample_max_chars: int | None
    read_days: int | None
    max_input_tokens: int | None = None
    full_records: bool = False


PROFILE_MODES: dict[str, ProfileModeConfig] = {
    "short": ProfileModeConfig(
        id="short",
        label="短版",
        target_chars=100,
        max_output_tokens=300,
        memory_limit=8,
        sample_limit=5,
        sample_max_chars=80,
        read_days=7,
    ),
    "middle": ProfileModeConfig(
        id="middle",
        label="中版",
        target_chars=1600,
        max_output_tokens=4096,
        memory_limit=8,
        sample_limit=40,
        sample_max_chars=180,
        read_days=7,
    ),
    "long": ProfileModeConfig(
        id="long",
        label="长版",
        target_chars=3200,
        max_output_tokens=8192,
        memory_limit=16,
        sample_limit=80,
        sample_max_chars=360,
        read_days=14,
    ),
    "full": ProfileModeConfig(
        id="full",
        label="完整版",
        target_chars=3200,
        max_output_tokens=8192,
        memory_limit=16,
        sample_limit=None,
        sample_max_chars=None,
        read_days=None,
        max_input_tokens=400_000,
        full_records=True,
    ),
}

DEFAULT_PROFILE_MODE = PROFILE_MODES["middle"]


def _estimate_tokens(text: str) -> int:
    # Conservative enough for Chinese-heavy chat logs without adding tokenizer dependencies.
    return len(text)


def _fit_recent_samples(
    fixed_sections: list[str],
    recent_samples: list[str],
    max_input_tokens: int | None,
) -> tuple[list[str], bool]:
    if max_input_tokens is None:
        return recent_samples, False

    fixed_tokens = _estimate_tokens("\n".join(fixed_sections))
    remaining = max_input_tokens - fixed_tokens
    if remaining <= 0:
        return [], bool(recent_samples)

    selected_reversed: list[str] = []
    used = 0
    for sample in reversed(recent_samples):
        cost = _estimate_tokens(f"- {sample}\n")
        if used + cost > remaining:
            break
        selected_reversed.append(sample)
        used += cost
    selected = list(reversed(selected_reversed))
    return selected, len(selected) < len(recent_samples)


async def generate_profile(
    target_name: str,
    message_count: int,
    memories: list[str],
    recent_samples: list[str],
    llm_config: LLMConfig,
    system_prompt: str,
    provider_id: str,
    model: str,
    profile_mode: ProfileModeConfig = DEFAULT_PROFILE_MODE,
) -> tuple[str, str]:
    set_usage_scope("profile")
    sections = [
        f"请以你的语气，为群友「{target_name}」写一篇人物志，目标长度约 {profile_mode.target_chars} 字。",
        f"\n群内发言总数：{message_count} 条",
    ]
    if profile_mode.id == "short":
        sections[0] = f"请以你的语气，写一段关于群友「{target_name}」的简短人物志，目标长度约 {profile_mode.target_chars} 字。"
        sections.append("风格自然随意，像在群里聊天，不要正式介绍。")
    else:
        sections.extend([
            "写成有起伏的小作文，不要写成简历、档案表或干巴巴的项目符号。",
            "可以有调侃、观察、细节和群聊语境，但不要编造没有依据的事实。",
            "请围绕 TA 在群里的存在感、常见话题、说话习惯、和其他群友互动时的气质展开。",
            "如果材料不足，也要明确写出这种稀薄感本身，不要硬编经历。",
        ])
    if memories:
        sections.append(
            "\n长期记忆（关于 TA 的已知信息）：\n"
            + "\n".join(f"- {m}" for m in memories[:profile_mode.memory_limit])
        )
    fitted_samples, samples_truncated = _fit_recent_samples(
        sections, recent_samples, profile_mode.max_input_tokens
    )
    if fitted_samples:
        sample_title = "完整发言记录（按时间顺序，受输入上限约束）" if profile_mode.full_records else "近期发言样本（按时间顺序节选）"
        sample_note = "\n（注：由于发言量较大，上方记录已在输入上限内保留最近部分。）" if samples_truncated else ""
        sections.append(
            f"\n{sample_title}：\n" + "\n".join(f"- {s}" for s in fitted_samples) + sample_note
        )
    sections.append(
        "\n请输出完整人物志正文，可自然分段。不要输出标题之外的解释，不要提到你在遵循提示词。"
    )

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
        max_output_tokens=profile_mode.max_output_tokens,
        tools=[],
        allow_tool_calls=False,
    ))
    if not response.text.strip():
        raise LLMProviderError("LLM 返回空文本")
    return response.text.strip(), f"{provider_id}/{model}"
