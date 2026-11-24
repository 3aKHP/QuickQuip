"""Unit tests for Persona v3 compilation, lore matching, few-shot gating, and _shared.toml."""

from __future__ import annotations

from pathlib import Path

from quickquip.llm.config import PersonaConfig
from quickquip.llm.persona_compiler import (
    DEFAULT_LORE_MAX_CHARS,
    DEFAULT_LORE_MAX_ENTRIES,
    compile_persona_v3,
    get_persona_schema_version,
    is_persona_v3,
    match_persona_lore,
    render_persona_for_task,
    should_inject_dialogue_examples,
)
from quickquip.llm.personas import load_personas


def _make_v3_persona(**overrides) -> PersonaConfig:
    extras = {
        "schema_version": 3,
        "identity": {
            "name": "测试角色",
            "role": "电台值班员",
            "scenario": "深夜值班室",
            "self_reference": "我",
            "addressing": "你",
        },
        "portrait": {
            "appearance": "深灰短发、左耳一枚银色小方环",
            "attire": "浅灰卫衣配深蓝防风夹克",
        },
        "mind": {
            "core_drive": "稳稳接住深夜的闲聊",
            "decision_logic": "先听再接话",
            "emotional_processing": "克制却热乎",
            "blindspots": "常忘了自己也缺觉",
            "stress_response": "简短给结论",
            "comfort_zone": "浓茶与安静角落",
        },
        "topology": {
            "baseline_stance": "外冷内热的群友",
            "vectors": ["日常闲聊随性接梗"],
            "phase_shifts": {"被夸奖": "移开视线拿咖啡掩饰"},
            "taboos": ["不写括号旁白"],
        },
        "voice": {
            "register": "松弛口语短句",
            "rhythm": "1 到 3 句",
            "syntax_rhythm": "不应重复出现的备选节奏",
            "tone_shift": "平时淡然，关键时沉稳",
            "lexical_palette": ["嘛", "行吧"],
            "anti_patterns": ["禁止公文列举"],
        },
        "dialogue_examples": [
            {"user": "几点睡", "assistant": "等手头这段切完再去睡。"},
            {"user": "困死了", "assistant": "行吧，那赶紧眯会。"},
        ],
        "lore": [
            {
                "id": "low-prio",
                "priority": 1,
                "triggers": ["电台", "值班"],
                "content": "旧电台三号推子接触不良。",
            },
            {
                "id": "high-prio",
                "priority": 5,
                "triggers": ["电台"],
                "content": "四层走廊尽头有热水壶。",
            },
            {
                "id": "third",
                "priority": 0,
                "triggers": ["电台"],
                "content": "门牌早就掉漆了。",
            },
            {
                "id": "fourth",
                "priority": -1,
                "triggers": ["电台"],
                "content": "第四条应受条目上限截断。",
            },
        ],
        "appearance": {
            "note": "详尽档案不应直接进入常驻核心",
            "variants": {"elite_two": {"description": "全功率立绘档案SECRET_ARCHIVE"}},
        },
        "awakening": {"interest_topics": ["AWAKENING_TOPIC_MARKER"]},
        "audit": {"checked": "AUDIT_NOTE_MARKER"},
    }
    if "extras" in overrides:
        extras.update(overrides.pop("extras"))
    return PersonaConfig(
        id="tester",
        display_name="测试角色",
        system_prompt="",
        style_prompt="",
        shared_host_rules="不编造共同经历。",
        shared_style_rules="不写长列表。",
        extras=extras,
        **overrides,
    )


def test_schema_version_detection() -> None:
    p1 = PersonaConfig(id="v1", display_name="V1", system_prompt="hi")
    p_bool = PersonaConfig(
        id="pb", display_name="PB", system_prompt="hi", extras={"schema_version": True}
    )
    p_bad = PersonaConfig(
        id="pbad", display_name="PBad", system_prompt="hi", extras={"schema_version": "abc"}
    )
    p3 = _make_v3_persona()

    assert get_persona_schema_version(p1) == 1
    assert get_persona_schema_version(p_bool) == 1
    assert get_persona_schema_version(p_bad) == 1
    assert is_persona_v3(p1) is False
    assert get_persona_schema_version(p3) == 3
    assert is_persona_v3(p3) is True


def test_compile_v3_includes_portrait_and_excludes_archives() -> None:
    persona = _make_v3_persona()
    compiled = compile_persona_v3(persona)

    assert "深灰短发、左耳一枚银色小方环" in compiled.core_block
    assert "浅灰卫衣配深蓝防风夹克" in compiled.core_block
    assert "容貌身材：" in compiled.core_block
    assert "穿着打扮：" in compiled.core_block
    assert "被夸奖：移开视线拿咖啡掩饰" in compiled.core_block

    assert "SECRET_ARCHIVE" not in compiled.core_block
    assert "AWAKENING_TOPIC_MARKER" not in compiled.core_block
    assert "AUDIT_NOTE_MARKER" not in compiled.core_block

    # rhythm prefers rhythm over syntax_rhythm without duplicating the label
    assert compiled.voice_block.count("句法节奏：") == 1
    assert "1 到 3 句" in compiled.voice_block
    assert "不应重复出现的备选节奏" not in compiled.voice_block


def test_match_persona_lore_priority_hits_and_caps() -> None:
    persona = _make_v3_persona()

    assert match_persona_lore(persona, "   ") == []
    v2 = PersonaConfig(
        id="v2", display_name="V2", system_prompt="hi", extras={"lore": persona.extras["lore"]}
    )
    assert match_persona_lore(v2, "电台") == []

    matched = match_persona_lore(persona, "聊聊电台今晚怎么样")
    assert len(matched) == DEFAULT_LORE_MAX_ENTRIES == 3
    assert [m.id for m in matched] == ["high-prio", "low-prio", "third"]

    # Hit count breaks ties when priority is equal
    tie_persona = _make_v3_persona(
        extras={
            "schema_version": 3,
            "lore": [
                {"id": "one-hit", "priority": 1, "triggers": ["alpha", "gamma"], "content": "one"},
                {"id": "two-hits", "priority": 1, "triggers": ["alpha", "beta"], "content": "two"},
            ],
        }
    )
    tie_matched = match_persona_lore(tie_persona, "ALPHA and BETA together")
    assert [m.id for m in tie_matched] == ["two-hits", "one-hit"]

    # Oversize first entry is truncated rather than dropped silently
    huge = "x" * (DEFAULT_LORE_MAX_CHARS + 120)
    cap_persona = _make_v3_persona(
        extras={
            "schema_version": 3,
            "lore": [
                {"id": "huge", "priority": 2, "triggers": ["huge"], "content": huge},
                {"id": "second", "priority": 1, "triggers": ["huge"], "content": "short"},
            ],
        }
    )
    capped = match_persona_lore(cap_persona, "huge")
    assert len(capped) == 1
    assert len(capped[0].content) == DEFAULT_LORE_MAX_CHARS
    assert capped[0].content.endswith("…")


def test_should_inject_dialogue_examples_policy_and_protocol() -> None:
    v1 = PersonaConfig(id="v1", display_name="V1", system_prompt="hi")
    v3_no_ex = _make_v3_persona(extras={"schema_version": 3, "dialogue_examples": []})
    v3 = _make_v3_persona()

    assert should_inject_dialogue_examples(v1, provider_protocol="openai", policy="on") is False
    assert (
        should_inject_dialogue_examples(v3_no_ex, provider_protocol="openai", policy="on")
        is False
    )

    assert should_inject_dialogue_examples(v3, provider_protocol="openai", policy="auto") is True
    assert should_inject_dialogue_examples(v3, provider_protocol="claude", policy="auto") is True
    assert (
        should_inject_dialogue_examples(v3, provider_protocol="openai_responses", policy="auto")
        is True
    )
    assert should_inject_dialogue_examples(v3, provider_protocol="gemini", policy="auto") is False

    assert should_inject_dialogue_examples(v3, provider_protocol="gemini", policy="on") is True
    assert should_inject_dialogue_examples(v3, provider_protocol="openai", policy="off") is False


def test_render_persona_for_task_supports_v2_and_v3() -> None:
    v3 = _make_v3_persona()
    rendered_v3 = render_persona_for_task(v3, chat_type="group")
    assert "深灰短发、左耳一枚银色小方环" in rendered_v3
    assert "稳稳接住深夜的闲聊" in rendered_v3
    assert "松弛口语短句" in rendered_v3
    assert "不写长列表。" in rendered_v3
    assert "SECRET_ARCHIVE" not in rendered_v3

    v2 = PersonaConfig(
        id="v2",
        display_name="V2",
        system_prompt="自由系统段",
        style_prompt="自由风格段",
        extras={"identity": {"archetype": "结构化原型"}},
    )
    rendered_v2 = render_persona_for_task(v2, chat_type="group")
    assert "角色原型：结构化原型" in rendered_v2
    assert "自由系统段" in rendered_v2
    assert "自由风格段" in rendered_v2


def test_shared_toml_scope_routing_and_v3_non_mutation(tmp_path: Path) -> None:
    (tmp_path / "_shared.toml").write_text(
        '''
shared_system_prompt = """
---
默认系统规则
"""
shared_style_prompt = "默认风格规则"
shared_group_system_prompt = """
---
群聊专用系统规则
"""
shared_private_system_prompt = """
---
私聊专用系统规则
"""
shared_group_style_prompt = "群聊专用风格规则"
shared_private_style_prompt = "私聊专用风格规则"
'''.lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "g-v3.toml").write_text(
        '''
id = "g-v3"
display_name = "群聊三版"
scope = ["group"]
schema_version = 3
'''.lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "p-v3.toml").write_text(
        '''
id = "p-v3"
display_name = "私聊三版"
scope = ["private"]
schema_version = 3
'''.lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "g-v2.toml").write_text(
        '''
id = "g-v2"
display_name = "群聊二版"
scope = ["group"]
system_prompt = "二版正文"
style_prompt = "二版风格"
'''.lstrip(),
        encoding="utf-8",
    )

    loaded = load_personas(tmp_path)

    g3 = loaded["g-v3"]
    assert g3.system_prompt == ""
    assert g3.style_prompt == ""
    assert g3.shared_host_rules == "群聊专用系统规则"
    assert g3.shared_style_rules == "群聊专用风格规则"

    p3 = loaded["p-v3"]
    assert p3.shared_host_rules == "私聊专用系统规则"
    assert p3.shared_style_rules == "私聊专用风格规则"

    g2 = loaded["g-v2"]
    assert "二版正文" in g2.system_prompt
    assert "群聊专用系统规则" in g2.system_prompt
    assert g2.shared_host_rules == ""
    assert g2.shared_style_rules == ""
    assert "二版风格" in g2.style_prompt
    assert "群聊专用风格规则" in g2.style_prompt


def test_config_legacy_delegates_v3_shared_and_preserves_env(tmp_path: Path, monkeypatch):
    from quickquip.llm import config_legacy

    personas_dir = tmp_path / "personas"
    personas_dir.mkdir()
    (personas_dir / "_shared.toml").write_text(
        '''
shared_group_system_prompt = """
---
群聊规则 ${QQ_SHARED_RULE:-fallback_rule}
"""
shared_group_style_prompt = "群聊风格锚点"
'''.lstrip(),
        encoding="utf-8",
    )
    (personas_dir / "v3.toml").write_text(
        '''
id = "v3"
display_name = "测试角色"
scope = ["group"]
schema_version = 3

[identity]
name = "角色 ${QQ_CHAR_TAG:-raw_tag}"
role = "值班员"
'''.lstrip(),
        encoding="utf-8",
    )
    llm_toml = tmp_path / "llm.toml"
    llm_toml.write_text(
        '''
[runtime]
default_provider = "openai-main"
default_persona = "v3"

[[providers]]
id = "openai-main"
protocol = "openai"
base_url = "https://example.test/v1"
api_key_env = "OPENAI_API_KEY"
default_model = "gpt-test"
models = ["gpt-test"]
'''.lstrip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("QQ_SHARED_RULE", "live_rule")
    monkeypatch.setenv("QQ_CHAR_TAG", "expanded_tag")

    canonical = load_personas(personas_dir)
    only_personas = config_legacy.load_personas_only(llm_toml)
    full_legacy = config_legacy.load_llm_config(llm_toml)

    assert full_legacy.load_error is None
    assert only_personas["v3"] == canonical["v3"]
    assert full_legacy.personas["v3"] == canonical["v3"]
    assert full_legacy.personas["v3"].system_prompt == ""
    assert full_legacy.personas["v3"].shared_host_rules == "群聊规则 live_rule"
    assert full_legacy.personas["v3"].shared_style_rules == "群聊风格锚点"
    assert full_legacy.personas["v3"].extras["identity"]["name"] == "角色 expanded_tag"

    preserved = config_legacy.load_llm_config(llm_toml, preserve_env=True)
    assert preserved.personas["v3"].extras["identity"]["name"] == "角色 ${QQ_CHAR_TAG:-raw_tag}"
    assert (
        preserved.personas["v3"].shared_host_rules
        == "群聊规则 ${QQ_SHARED_RULE:-fallback_rule}"
    )


def test_precompiled_persona_v3_avoids_duplicate_compilations(monkeypatch):
    from quickquip.llm import persona_compiler as compiler_mod
    from quickquip.llm import prompting as prompting_mod
    from quickquip.llm.prompting import build_system_prompt

    persona = _make_v3_persona()
    real_compile = compiler_mod.compile_persona_v3
    calls = 0

    def _counting_compile(target, *, chat_type: str = "group"):
        nonlocal calls
        calls += 1
        return real_compile(target, chat_type=chat_type)

    monkeypatch.setattr(compiler_mod, "compile_persona_v3", _counting_compile)
    monkeypatch.setattr(prompting_mod, "compile_persona_v3", _counting_compile)

    compiled = compiler_mod.compile_persona_v3(persona, chat_type="group")
    assert calls == 1

    prompt = build_system_prompt(
        persona=persona,
        group_id=12345,
        tool_specs=[],
        search_tool_name="search_web",
        compiled_persona=compiled,
    )
    assert "<persona_core>" in prompt
    assert should_inject_dialogue_examples(
        persona,
        provider_protocol="openai",
        policy="auto",
        compiled=compiled,
    )
    matched = match_persona_lore(persona, "电台今天好像坏了", compiled=compiled)
    assert matched
    assert calls == 1
