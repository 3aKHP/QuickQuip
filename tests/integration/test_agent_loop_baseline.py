"""1.15 五 Turn 主例验收（原基线缺口测试，阶段 E 落地后转为正向断言）。

§11.2 五轮主例：五 Turn/七调用，前四轮普通正文先于所属工具执行外发；
末 Turn 三段，共七文字 Chunk；下次请求有完整允许的工具事实。
默认配置下末 Turn 374 字符保持一段（阈值 800）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from plugins.llm_runtime import LLMService
from tests.fixtures.agent_loop import (
    AGENT_LOOP_TEST_SPLIT,
    FIVE_TURN_TEXTS,
    CollectingSink,
    FiveTurnScenarioClient,
    build_legacy_db,
    five_turn_tool_calls,
)
from tests.fixtures.configs import write_llm_config_bundle


def _scenario_toml(base_toml: str) -> str:
    # 五 Turn 场景需要 4 个工具轮次；默认 fixture 配置 tool_max_rounds=2。
    return base_toml.replace("tool_max_rounds = 2", "tool_max_rounds = 8")


@pytest.fixture
def scenario_service(tmp_path: Path) -> LLMService:
    from tests.fixtures.configs import MIN_LLM_CONFIG_TOML

    paths = write_llm_config_bundle(
        tmp_path, config_toml=_scenario_toml(MIN_LLM_CONFIG_TOML)
    )
    return LLMService(**paths)


@pytest.fixture
def patch_scenario_provider(scenario_service, patch_provider_builder):
    def _patch(protocol: str = "openai") -> FiveTurnScenarioClient:
        client = FiveTurnScenarioClient(protocol=protocol)
        patch_provider_builder(lambda provider: client)
        return client

    return _patch


async def run_five_turn_scenario(service: LLMService, **kwargs) -> dict:
    return await service.generate_reply(
        group_id=1001,
        user_id="2002",
        sender_name="镜子",
        prompt="K甲夏季赛现在赛况如何？",
        **kwargs,
    )


# ── fixture 契约自检 ────────────────────────────────────────────────


def test_five_turn_fixture_contract():
    assert [len(text) for text in FIVE_TURN_TEXTS] == [32, 31, 50, 31, 374]
    batches = five_turn_tool_calls()
    assert [len(batch) for batch in batches] == [1, 2, 2, 2, 0]
    assert sum(len(batch) for batch in batches) == 7
    # 末 Turn 必须存在空行分界：测试切分参数下形成三段的前提。
    assert FIVE_TURN_TEXTS[4].count("\n\n") == 2


def test_legacy_fixture_rows_cover_migration_groups(tmp_path: Path):
    db_path = tmp_path / "llm.db"
    build_legacy_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT role, message_id FROM conversation_messages ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert [role for role, _ in rows] == [
        "assistant", "user", "assistant", "user", "user", "assistant",
    ]
    assert [mid for _, mid in rows if mid is not None] == ["m3"]


# ── 默认关闭开关：完整记录 + 最终单发（§6.3） ───────────────────────


async def test_final_only_mode_records_every_turn_and_sends_final(
    scenario_service, patch_scenario_provider
):
    client = patch_scenario_provider("openai")
    result = await run_five_turn_scenario(scenario_service)

    assert len(client.requests) == 5
    rows = scenario_service.store.list_recent_conversation_messages(1001, limit=50)
    assistant_rows = [row for row in rows if row["role"] == "assistant"]
    # 每个已提交 Turn 落一条 assistant 行（§3.2）。
    assert [row["content"] for row in assistant_rows] == list(FIVE_TURN_TEXTS)
    # 最终正文沿现有单次交付方式。
    assert result["reply"] == FIVE_TURN_TEXTS[4]
    # 非最终正文标记 suppressed_by_policy；最终 Turn 在关闭模式下不建交付行
    #（最终正文沿现有单次交付，回执由兼容列回填记录）。
    with scenario_service.store._connect() as conn:
        statuses = [
            row["status"]
            for row in conn.execute(
                "SELECT status FROM agent_deliveries WHERE kind='text_chunk' ORDER BY delivery_index"
            )
        ]
    assert statuses == ["suppressed", "suppressed", "suppressed", "suppressed"]
    # 七次工具调用全部有终态。
    with scenario_service.store._connect() as conn:
        tool_rows = conn.execute(
            "SELECT status FROM agent_tool_executions"
        ).fetchall()
    assert len(tool_rows) == 7
    assert all(row["status"] == "succeeded" for row in tool_rows)


# ── 开启开关：七文字 Chunk + 逐 Turn 交付（§11.2 主例验收） ─────────


async def test_all_turns_mode_seven_chunks_delivered_before_tools(
    scenario_service, patch_scenario_provider, monkeypatch
):
    monkeypatch.setattr(
        scenario_service.config.runtime, "agent_delivery_enabled", True
    )
    monkeypatch.setattr(
        scenario_service.config.runtime,
        "reply_split_threshold_chars",
        AGENT_LOOP_TEST_SPLIT["threshold"],
    )
    monkeypatch.setattr(
        scenario_service.config.runtime,
        "reply_chunk_max_chars",
        AGENT_LOOP_TEST_SPLIT["chunk_max"],
    )
    sink = CollectingSink()
    scenario_service.bind_delivery_sink(sink)
    patch_scenario_provider("openai")

    result = await run_five_turn_scenario(scenario_service)

    # 七个文字 Chunk（4 Turn × 1 + 末 Turn 3）。
    assert len(sink.deliveries) == 7
    # 前四轮普通正文先于所属工具执行外发：每轮首个 delivery 的文本 == 该轮正文。
    turn_texts = [FIVE_TURN_TEXTS[i] for i in range(5)]
    delivered_first_texts = [payload["text"] for _, payload in sink.deliveries[:4]]
    assert delivered_first_texts == turn_texts[:4]
    # 末 Turn 三段还原恒等。
    final_chunks = [payload["text"] for _, payload in sink.deliveries[4:]]
    assert "".join(final_chunks) == FIVE_TURN_TEXTS[4]
    # reply 不再二次发送。
    assert result["reply"] == ""
    # 默认配置对照：不开测试切分参数时末 Turn 374 字符保持一段。
    with scenario_service.store._connect() as conn:
        chunk_count = conn.execute(
            "SELECT COUNT(*) FROM agent_deliveries WHERE kind = 'text_chunk'"
        ).fetchone()[0]
    assert chunk_count == 7


# ── 重放：下次请求携带完整工具事实（§11.2） ─────────────────────────


async def test_next_request_replays_full_tool_facts(
    scenario_service, patch_scenario_provider
):
    patch_scenario_provider("openai")
    await run_five_turn_scenario(scenario_service)

    sink = CollectingSink()
    scenario_service.bind_delivery_sink(sink)

    class SecondRoundClient:
        def __init__(self) -> None:
            self.request = None

        async def complete(self, request):
            self.request = request
            from quickquip.llm.provider import LLMResponse

            return LLMResponse(text="汇总完毕。", model=request.model)

    second = SecondRoundClient()
    import quickquip.llm.service as service_module

    original = service_module.build_provider_client
    service_module.build_provider_client = lambda provider: second
    try:
        await scenario_service.generate_reply(
            group_id=1001, user_id="4004", sender_name="4s", prompt="总结一下。"
        )
    finally:
        service_module.build_provider_client = original

    request = second.request
    tool_messages = [m for m in request.messages if m.role == "tool"]
    assert len(tool_messages) == 7  # 完整允许的工具事实
    assistant_calls = [m for m in request.messages if m.role == "assistant" and m.tool_calls]
    assert len(assistant_calls) == 4
