"""Persona v3 compiler, on-demand lore matcher, and task persona renderer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from quickquip.llm.config import PersonaConfig

DEFAULT_LORE_MAX_ENTRIES = 3
DEFAULT_LORE_MAX_CHARS = 800
MAX_DIALOGUE_EXAMPLES = 4


@dataclass(frozen=True, slots=True)
class PersonaLoreEntry:
    id: str
    triggers: tuple[str, ...]
    content: str
    priority: int = 0


@dataclass(frozen=True, slots=True)
class PersonaDialogueExample:
    user: str
    assistant: str
    context: str = ""


@dataclass(frozen=True, slots=True)
class PersonaV3Compiled:
    core_block: str
    voice_block: str
    dialogue_examples: tuple[PersonaDialogueExample, ...]
    lore_entries: tuple[PersonaLoreEntry, ...]


def get_persona_schema_version(persona: PersonaConfig) -> int:
    raw = getattr(persona, "extras", {}).get("schema_version", 1)
    if isinstance(raw, bool):
        return 1
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 1


def is_persona_v3(persona: PersonaConfig) -> bool:
    return get_persona_schema_version(persona) >= 3


def _render_labeled_fields(
    table: Mapping[str, Any],
    field_labels: Sequence[tuple[str, str]],
) -> str:
    lines: list[str] = []
    for key, label in field_labels:
        value = table.get(key)
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                lines.append(f"{label}：{cleaned}")
        elif value:
            lines.append(f"{label}：{value}")
    return "\n".join(lines)


def _render_string_list(items: Any, heading: str) -> str:
    if isinstance(items, str):
        cleaned = items.strip()
        return f"{heading}：{cleaned}" if cleaned else ""
    if not isinstance(items, list):
        return ""
    lines = [str(item).strip() for item in items if str(item).strip()]
    if not lines:
        return ""
    return f"{heading}：\n" + "\n".join(f"- {item}" for item in lines)


def _render_phase_shifts(raw: Any) -> str:
    if isinstance(raw, Mapping):
        lines = [
            f"- {str(trigger).strip()}：{str(shift).strip()}"
            for trigger, shift in raw.items()
            if str(trigger).strip() and str(shift).strip()
        ]
        return ("情境切换：\n" + "\n".join(lines)) if lines else ""
    return _render_string_list(raw, "情境切换")


def _parse_dialogue_examples(raw: Any) -> tuple[PersonaDialogueExample, ...]:
    if not isinstance(raw, list):
        return ()
    parsed: list[PersonaDialogueExample] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        user_text = str(item.get("user", "")).strip()
        assistant_text = str(item.get("assistant", "")).strip()
        if not user_text or not assistant_text:
            continue
        context_text = str(item.get("context", "")).strip()
        parsed.append(
            PersonaDialogueExample(
                user=user_text,
                assistant=assistant_text,
                context=context_text,
            )
        )
        if len(parsed) >= MAX_DIALOGUE_EXAMPLES:
            break
    return tuple(parsed)


def _parse_lore_entries(raw: Any) -> tuple[PersonaLoreEntry, ...]:
    if not isinstance(raw, list):
        return ()
    parsed: list[PersonaLoreEntry] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, Mapping):
            continue
        content = str(item.get("content", "")).strip()
        raw_triggers = item.get("triggers", [])
        if isinstance(raw_triggers, str):
            raw_triggers = [raw_triggers]
        if not isinstance(raw_triggers, list):
            continue
        triggers = tuple(str(t).strip() for t in raw_triggers if str(t).strip())
        if not content or not triggers:
            continue
        entry_id = str(item.get("id", "")).strip() or f"lore-{index}"
        try:
            priority = int(item.get("priority", 0))
        except (TypeError, ValueError):
            priority = 0
        parsed.append(
            PersonaLoreEntry(
                id=entry_id,
                triggers=triggers,
                content=content,
                priority=priority,
            )
        )
    return tuple(parsed)


def compile_persona_v3(
    persona: PersonaConfig, *, chat_type: str = "group"
) -> PersonaV3Compiled:
    """Compile Persona v3 tables into compact core, voice, examples, and lore.

    Exhaustive multi-variant ``[appearance]`` archives, ``[awakening]`` topics,
    and ``[audit]`` notes stay excluded from always-loaded prompt text, while
    concise ``[portrait].appearance`` and ``[portrait].attire`` remain anchored.
    """
    extras = getattr(persona, "extras", {}) or {}
    core_sections: list[str] = []

    identity = extras.get("identity")
    if isinstance(identity, Mapping):
        id_parts: list[str] = []
        name = str(identity.get("name") or getattr(persona, "display_name", "") or "").strip()
        if name:
            id_parts.append(f"角色名：{name}")
        role = str(identity.get("role") or identity.get("archetype") or "").strip()
        if role:
            id_parts.append(f"核心定位：{role}")
        extra_identity = _render_labeled_fields(
            identity,
            (
                ("scenario", "当前情境"),
                ("self_reference", "自称方式"),
                ("addressing", "称呼对方"),
            ),
        )
        if extra_identity:
            id_parts.append(extra_identity)
        if id_parts:
            core_sections.append("\n".join(id_parts))

    portrait = extras.get("portrait")
    if isinstance(portrait, Mapping):
        portrait_body = _render_labeled_fields(
            portrait,
            (
                ("appearance", "容貌身材"),
                ("attire", "穿着打扮"),
            ),
        )
        if portrait_body:
            core_sections.append(
                "自身外貌与衣着（用于保持视觉与日常细节一致，无需主动背诵衣饰细节）：\n"
                + portrait_body
            )

    mind = extras.get("mind")
    if isinstance(mind, Mapping):
        mind_body = _render_labeled_fields(
            mind,
            (
                ("core_drive", "核心驱动"),
                ("decision_logic", "判断与行动逻辑"),
                ("emotional_processing", "情绪质感"),
                ("blindspots", "盲点与弱点"),
                ("stress_response", "高压反应"),
                ("comfort_zone", "舒适区"),
            ),
        )
        if mind_body:
            core_sections.append(mind_body)

    topology = extras.get("topology")
    if isinstance(topology, Mapping):
        topo_parts: list[str] = []
        stance = str(topology.get("baseline_stance", "")).strip()
        if stance:
            topo_parts.append(f"基准立场：{stance}")
        vectors = _render_string_list(topology.get("vectors"), "核心关系与行为向量")
        if vectors:
            topo_parts.append(vectors)
        shifts = _render_phase_shifts(topology.get("phase_shifts"))
        if shifts:
            topo_parts.append(shifts)
        taboos = _render_string_list(topology.get("taboos"), "OOC 与行为禁忌")
        if taboos:
            topo_parts.append(taboos)
        if topo_parts:
            core_sections.append("\n\n".join(topo_parts))

    free_system = str(getattr(persona, "system_prompt", "") or "").strip()
    if free_system:
        core_sections.append(free_system)

    voice_sections: list[str] = []
    voice = extras.get("voice")
    if isinstance(voice, Mapping):
        voice_parts: list[str] = []
        rhythm_value = voice.get("rhythm") or voice.get("syntax_rhythm")
        voice_view = dict(voice)
        if rhythm_value:
            voice_view["rhythm"] = rhythm_value
        voice_scalars = _render_labeled_fields(
            voice_view,
            (
                ("register", "核心声腔"),
                ("rhythm", "句法节奏"),
                ("tone_shift", "语气切换"),
            ),
        )
        if voice_scalars:
            voice_parts.append(voice_scalars)
        palette = _render_string_list(
            voice.get("lexical_palette") or voice.get("verbal_habits"),
            "自然语感词库（仅作气质底色低频自然带出，严禁每句套用或机械复读）",
        )
        if palette:
            voice_parts.append(palette)
        anti = _render_string_list(
            voice.get("anti_patterns") or voice.get("verbal_constraints"),
            "语言禁区",
        )
        if anti:
            voice_parts.append(anti)
        if voice_parts:
            voice_sections.append("\n".join(voice_parts))

    free_style = str(getattr(persona, "style_prompt", "") or "").strip()
    if free_style:
        voice_sections.append(free_style)

    # Note: chat_type is accepted for future channel-specific tuning and call-site symmetry.
    _ = chat_type

    return PersonaV3Compiled(
        core_block="\n\n".join(section for section in core_sections if section),
        voice_block="\n\n".join(section for section in voice_sections if section),
        dialogue_examples=_parse_dialogue_examples(extras.get("dialogue_examples")),
        lore_entries=_parse_lore_entries(extras.get("lore")),
    )


def match_persona_lore(
    persona: PersonaConfig,
    text: str,
    *,
    max_entries: int = DEFAULT_LORE_MAX_ENTRIES,
    max_chars: int = DEFAULT_LORE_MAX_CHARS,
    compiled: PersonaV3Compiled | None = None,
) -> list[PersonaLoreEntry]:
    """Match on-demand ``[[lore]]`` entries against turn text within budget."""
    if not is_persona_v3(persona) or not text.strip():
        return []
    if max_entries <= 0 or max_chars <= 0:
        return []

    target = compiled if compiled is not None else compile_persona_v3(persona)
    lore_entries = target.lore_entries
    if not lore_entries:
        return []

    haystack = text.casefold()
    scored: list[tuple[int, int, int, PersonaLoreEntry]] = []
    for index, entry in enumerate(lore_entries):
        hits = sum(1 for trigger in entry.triggers if trigger.casefold() in haystack)
        if hits > 0:
            scored.append((-entry.priority, -hits, index, entry))

    if not scored:
        return []

    scored.sort(key=lambda item: (item[0], item[1], item[2]))

    selected: list[PersonaLoreEntry] = []
    used_chars = 0
    for _, _, _, entry in scored:
        if len(selected) >= max_entries:
            break
        entry_len = len(entry.content)
        if entry_len > max_chars:
            if not selected:
                truncated = (
                    entry.content[: max_chars - 1].rstrip() + "…"
                    if max_chars > 1
                    else entry.content[:max_chars]
                )
                selected.append(
                    PersonaLoreEntry(
                        id=entry.id,
                        triggers=entry.triggers,
                        content=truncated,
                        priority=entry.priority,
                    )
                )
                used_chars += len(truncated)
            continue
        if used_chars + entry_len > max_chars:
            continue
        selected.append(entry)
        used_chars += entry_len

    return selected


def should_inject_dialogue_examples(
    persona: PersonaConfig,
    *,
    provider_protocol: str,
    policy: str = "auto",
    compiled: PersonaV3Compiled | None = None,
) -> bool:
    """Decide whether Persona v3 ``[[dialogue_examples]]`` should be injected."""
    if not is_persona_v3(persona):
        return False
    target = compiled if compiled is not None else compile_persona_v3(persona)
    if not target.dialogue_examples:
        return False
    normalized = (policy or "auto").strip().lower()
    if normalized == "off":
        return False
    if normalized == "on":
        return True
    return (provider_protocol or "").strip().lower() != "gemini"


def render_persona_for_task(
    persona: PersonaConfig, *, chat_type: str = "group"
) -> str:
    """Render full persona core + voice for non-chat tasks (briefing, summary, profile)."""
    if is_persona_v3(persona):
        compiled = compile_persona_v3(persona, chat_type=chat_type)
        parts = [
            compiled.core_block,
            compiled.voice_block,
            str(getattr(persona, "shared_style_rules", "") or "").strip(),
        ]
        return "\n\n".join(part for part in parts if part)

    from quickquip.llm.prompting import _compile_structured_persona

    structured = _compile_structured_persona(getattr(persona, "extras", {}))
    parts = [
        structured,
        str(getattr(persona, "system_prompt", "") or "").strip(),
        str(getattr(persona, "style_prompt", "") or "").strip(),
    ]
    return "\n\n".join(part for part in parts if part)
