"""按会话 opt-in 的分段交付：两域独立覆盖优先于全局默认。

行为矩阵（中间轮 × 最终轮）四组合全部钉死；与 test_agent_loop_baseline.py
的差别：那边钉全局开关的行为，这边钉 per-scope 覆盖的解析与生效。每次
运行用独立 scope：五 Turn 剧本客户端按请求内 assistant 行数计轮次，
同 scope 复跑会耗尽剧本。
"""
from __future__ import annotations

from pathlib import Path

from plugins.llm_runtime import LLMService
from tests.fixtures.agent_loop import (
    AGENT_LOOP_TEST_SPLIT,
    FIVE_TURN_TEXTS,
    CollectingSink,
    FiveTurnScenarioClient,
)
from tests.fixtures.configs import MIN_LLM_CONFIG_TOML, write_llm_config_bundle


async def _service(tmp_path: Path) -> LLMService:
    paths = write_llm_config_bundle(
        tmp_path,
        config_toml=MIN_LLM_CONFIG_TOML.replace("tool_max_rounds = 2", "tool_max_rounds = 8"),
    )
    service = LLMService(**paths)
    for attr, value in [
        ("reply_split_threshold_chars", AGENT_LOOP_TEST_SPLIT["threshold"]),
        ("reply_chunk_max_chars", AGENT_LOOP_TEST_SPLIT["chunk_max"]),
    ]:
        setattr(service.config.runtime, attr, value)
    return service


async def _run(service: LLMService, patch_provider_builder, group_id: int) -> tuple[dict, CollectingSink]:
    sink = CollectingSink()
    service.bind_delivery_sink(sink)
    client = FiveTurnScenarioClient(protocol="openai")
    patch_provider_builder(lambda provider: client)
    result = await service.generate_reply(
        group_id=group_id, user_id="2002", sender_name="镜子", prompt="K甲赛况如何？",
    )
    return result, sink


def _sink_texts(sink: CollectingSink) -> list[str]:
    return [str(payload.get("text", "")) for _, payload in sink.deliveries]


async def test_delivery_matrix_all_four_combos(tmp_path: Path, patch_provider_builder):
    """两域独立：A 双关 / B 中间开 / C 最终开 / D 双开，行为各自符合定义。"""
    service = await _service(tmp_path)

    # A：全局默认双关，无覆盖 → 中间轮 suppressed，最终正文单发
    result_a, sink_a = await _run(service, patch_provider_builder, group_id=1001)
    assert sink_a.deliveries == []
    assert result_a["reply"] == FIVE_TURN_TEXTS[4]
    # recorder 仍工作：精确回填键齐全（最终单发路径）。
    assert result_a["agent_turn_row_id"] is not None
    assert result_a["scope_key"] == "1001"

    # B：仅中间轮开 → 四个中间 Turn 各一段经 sink，最终正文仍整条单发
    service.set_chat_agent_delivery_enabled(1002, True, chat_type="group", domain="intermediate")
    result_b, sink_b = await _run(service, patch_provider_builder, group_id=1002)
    assert _sink_texts(sink_b) == [text.rstrip() for text in FIVE_TURN_TEXTS[:4]]
    assert result_b["reply"] == FIVE_TURN_TEXTS[4]

    # C：仅最终轮开 → 中间轮 suppressed 不外发（回归防线），最终三段经 sink
    service.set_chat_agent_delivery_enabled(1003, True, chat_type="group", domain="final")
    result_c, sink_c = await _run(service, patch_provider_builder, group_id=1003)
    assert len(sink_c.deliveries) == 3
    assert all(
        text not in _sink_texts(sink_c)
        for text in (FIVE_TURN_TEXTS[0], FIVE_TURN_TEXTS[1], FIVE_TURN_TEXTS[2], FIVE_TURN_TEXTS[3])
    ), "中间轮关闭时 suppressed 正文不得进入 sink"
    assert "".join(_sink_texts(sink_c)) == "".join(
        FIVE_TURN_TEXTS[4].split("\n\n")
    ), "最终三段拼回应等于源正文（按空行分界）"
    assert result_c["reply"] == ""

    # D：双开 → 4 + 3 = 7 段全量交付，reply 置空
    service.set_chat_agent_delivery_enabled(1004, True, chat_type="group", domain="all")
    result_d, sink_d = await _run(service, patch_provider_builder, group_id=1004)
    assert len(sink_d.deliveries) == 7
    assert result_d["reply"] == ""


async def test_delivery_override_false_beats_global_on_and_reset_follows(
    tmp_path: Path, patch_provider_builder
):
    """单域覆盖关优先于全局开；reset 单域只影响该域，另一域覆盖保留。"""
    service = await _service(tmp_path)
    service.config.runtime.agent_delivery_intermediate_enabled = True
    service.config.runtime.agent_delivery_final_enabled = True

    service.set_chat_agent_delivery_enabled(1001, False, chat_type="group", domain="intermediate")
    result, sink = await _run(service, patch_provider_builder, group_id=1001)
    # 全局双开 + 中间轮覆盖关 = 组合 C
    assert len(sink.deliveries) == 3
    assert result["reply"] == ""

    service.set_chat_agent_delivery_enabled(1001, None, chat_type="group", domain="intermediate")
    override = service.store.get_group_settings("1001")
    assert override.agent_delivery_intermediate is None
    assert override.agent_delivery_final is None
    result2, sink2 = await _run(service, patch_provider_builder, group_id=1003)
    # 覆盖清空后跟随全局双开 = 组合 D
    assert len(sink2.deliveries) == 7
    assert result2["reply"] == ""
