"""1.15 基线缺口核对（实施计划 §12.A）。

本文件在当前实现上固定两件事：

1. **fixture 契约自检**——五 Turn 主例的正文长度（32/31/50/31/374 code
   point）与七次工具调用分布，防止 fixture 漂移破坏 §11.2 的验收计数。
2. **基线缺口特征化**——五 Turn 场景跑在当前实现上，仅末 Turn 正文进入
   history（一条 assistant 行），中间四个 Turn 的普通正文既不落库也无
   交付记录。特征化测试锁定现状；带 ``xfail(strict=True)`` 的目标测试
   声明 1.15 契约，实现落地后 XPASS 会强制摘除标记。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from plugins.llm_runtime import LLMService
from tests.fixtures.agent_loop import (
    AGENT_LOOP_TEST_SPLIT,
    FIVE_TURN_TEXTS,
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


async def run_five_turn_scenario(service: LLMService) -> dict:
    return await service.generate_reply(
        group_id=1001,
        user_id="2002",
        sender_name="镜子",
        prompt="K甲夏季赛现在赛况如何？",
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
    # 无 receipt 的 assistant（legacy_untracked）与带 receipt 的（sent）各一。
    assert [mid for _, mid in rows if mid is not None] == ["m3"]


# ── 基线缺口特征化（当前实现的事实，实现落地后改写为目标断言） ─────────


async def test_baseline_only_final_turn_text_persists(
    scenario_service, patch_scenario_provider
):
    """当前实现：五 Turn 场景只有末 Turn 正文落库为一条 assistant 行。"""
    client = patch_scenario_provider("openai")
    assert len(client.requests) == 0  # 场景尚未跑

    result = await run_five_turn_scenario(scenario_service)

    # 五次模型请求确实发生（五 Turn 都完整收到）。
    assert len(client.requests) == 5
    # 但 history 只落了一条 assistant 行，内容 = 末 Turn 正文。
    rows = scenario_service.store.list_recent_conversation_messages(1001, limit=50)
    assistant_rows = [row for row in rows if row["role"] == "assistant"]
    assert len(assistant_rows) == 1
    assert assistant_rows[0]["content"] == FIVE_TURN_TEXTS[4]
    # 前四个 Turn 的普通正文（32/31/50/31 cp）不在任何持久化正文中。
    persisted = "\n".join(row["content"] for row in rows)
    for text in FIVE_TURN_TEXTS[:4]:
        assert text not in persisted
    # 交付缺口同样存在：reply 只含末 Turn 正文。
    assert result["reply"] == FIVE_TURN_TEXTS[4]


@pytest.mark.xfail(
    reason="1.15 目标：每个已提交 Turn 落一条 assistant 行（§3.2/§12.B）",
    strict=True,
)
async def test_target_every_turn_persists_assistant_row(
    scenario_service, patch_scenario_provider
):
    patch_scenario_provider("openai")
    await run_five_turn_scenario(scenario_service)

    rows = scenario_service.store.list_recent_conversation_messages(1001, limit=50)
    assistant_rows = [row for row in rows if row["role"] == "assistant"]
    assert [row["content"] for row in assistant_rows] == list(FIVE_TURN_TEXTS)


@pytest.mark.xfail(
    reason="1.15 目标：Loop/Turn/工具/交付侧表与逐 Turn 关联（§4.1/§12.B）",
    strict=True,
)
async def test_target_agent_loop_side_tables_exist(
    scenario_service, patch_scenario_provider
):
    patch_scenario_provider("openai")
    await run_five_turn_scenario(scenario_service)

    store = scenario_service.store
    with store._connect() as conn:
        loop_count = conn.execute("SELECT COUNT(*) FROM agent_loops").fetchone()[0]
    assert loop_count == 1


@pytest.mark.xfail(
    reason="1.15 目标：测试切分参数下七文字 Chunk（§11.2 五轮主例验收）",
    strict=True,
)
async def test_target_seven_text_chunks_with_test_split(
    scenario_service, patch_scenario_provider, monkeypatch
):
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
    patch_scenario_provider("openai")
    result = await run_five_turn_scenario(scenario_service)

    with scenario_service.store._connect() as conn:
        chunk_count = conn.execute(
            "SELECT COUNT(*) FROM agent_deliveries WHERE kind = 'text_chunk'"
        ).fetchone()[0]
    assert chunk_count == 7
    assert result["reply"] == ""  # 逐 Turn 模式下 reply 不再二次发送
