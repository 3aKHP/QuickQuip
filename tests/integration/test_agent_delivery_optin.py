"""按会话 opt-in 的分段交付：三态覆盖优先于全局默认，两个方向都验证。

覆盖开/关优先于全局；未覆盖（reset/NULL）跟随全局默认。与
test_agent_loop_baseline.py 的差别：那边钉全局开关的行为，这边钉
per-scope 覆盖的解析与生效。每次运行用独立 scope：五 Turn 剧本客户端
按请求内 assistant 行数计轮次，同 scope 复跑会耗尽剧本。
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


async def test_delivery_default_off_and_group_override_enables(
    tmp_path: Path, patch_provider_builder
):
    """全局默认关：无覆盖走单发；覆盖开的群分段交付。"""
    service = await _service(tmp_path)

    result, sink = await _run(service, patch_provider_builder, group_id=1001)
    assert sink.deliveries == []
    assert result["reply"] == FIVE_TURN_TEXTS[4]
    # recorder 仍工作：精确回填键齐全（关闭模式沿现有单发交付）。
    assert result["agent_turn_row_id"] is not None
    assert result["scope_key"] == "1001"

    service.set_chat_agent_delivery_enabled(1002, True, chat_type="group")
    result2, sink2 = await _run(service, patch_provider_builder, group_id=1002)
    assert len(sink2.deliveries) == 7
    assert result2["reply"] == ""


async def test_delivery_override_false_beats_global_on_and_reset_follows(
    tmp_path: Path, patch_provider_builder
):
    """群覆盖关优先于全局开；清空覆盖后跟随全局。"""
    service = await _service(tmp_path)
    service.config.runtime.agent_delivery_enabled = True

    service.set_chat_agent_delivery_enabled(1001, False, chat_type="group")
    result, sink = await _run(service, patch_provider_builder, group_id=1001)
    assert sink.deliveries == []
    assert result["reply"] == FIVE_TURN_TEXTS[4]

    service.set_chat_agent_delivery_enabled(1001, None, chat_type="group")
    assert service.store.get_group_settings("1001").agent_delivery_enabled is None
    result2, sink2 = await _run(service, patch_provider_builder, group_id=1003)
    assert len(sink2.deliveries) == 7
    assert result2["reply"] == ""
