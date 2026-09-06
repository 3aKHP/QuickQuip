"""§11.2 交付失败测试组：D3 策略准确，unknown 不重发。"""
from __future__ import annotations

from pathlib import Path

from plugins.llm_runtime import LLMService
from quickquip.llm.agent_records import (
    DeliveryReceipt,
    DeliveryStatus,
)
from tests.fixtures.agent_loop import AGENT_LOOP_TEST_SPLIT, FIVE_TURN_TEXTS
from tests.fixtures.configs import write_llm_config_bundle


class ScriptedSink:
    """按脚本回执的 sink：记录全部交付尝试。"""

    def __init__(self, script: list[DeliveryReceipt]):
        self.script = list(script)
        self.attempts: list[tuple[str, str]] = []

    async def __call__(self, delivery_id: str, payload: dict) -> DeliveryReceipt:
        self.attempts.append((delivery_id, str(payload.get("text", ""))[:20]))
        return self.script.pop(0) if self.script else DeliveryReceipt(
            status=DeliveryStatus.SENT, message_id="auto"
        )


async def _service(tmp_path: Path) -> LLMService:
    paths = write_llm_config_bundle(
        tmp_path,
        config_toml=write_llm_config_bundle.__globals__["MIN_LLM_CONFIG_TOML"].replace(
            "tool_max_rounds = 2", "tool_max_rounds = 8"
        ),
    )
    return LLMService(**paths)


async def test_first_chunk_failure_stops_tools_and_generation(
    tmp_path: Path, patch_provider_builder
):
    """首段 failed：终止后续发送、工具启动和模型生成（D3）。"""
    from tests.fixtures.agent_loop import FiveTurnScenarioClient

    service = await _service(tmp_path)
    for attr, value in [
        ("agent_delivery_enabled", True),
        ("reply_split_threshold_chars", AGENT_LOOP_TEST_SPLIT["threshold"]),
        ("reply_chunk_max_chars", AGENT_LOOP_TEST_SPLIT["chunk_max"]),
    ]:
        setattr(service.config.runtime, attr, value)
    sink = ScriptedSink([DeliveryReceipt(status=DeliveryStatus.FAILED, error_code="NetworkError")])
    service.bind_delivery_sink(sink)
    client = FiveTurnScenarioClient(protocol="openai")
    patch_provider_builder(lambda provider: client)

    result = await service.generate_reply(
        group_id=1001, user_id="2002", sender_name="镜子", prompt="K甲赛况如何？",
    )

    # 首段失败后：只有一次发送尝试，无第二次模型请求，无工具执行记录。
    assert len(sink.attempts) == 1
    assert len(client.requests) == 1
    assert result["reply"] == ""
    with service.store._connect() as conn:
        tool_status = [row["status"] for row in conn.execute("SELECT status FROM agent_tool_executions")]
        loop_row = conn.execute(
            "SELECT status, terminal_reason FROM agent_loops"
        ).fetchone()
        delivery_status = [
            row["status"]
            for row in conn.execute("SELECT status FROM agent_deliveries ORDER BY delivery_index")
        ]
    assert tool_status == ["not_executed"]  # 批次内声明有终态、未启动
    assert loop_row["status"] == "interrupted"
    assert loop_row["terminal_reason"] == "delivery_failed"
    assert delivery_status[0] == "failed"
    assert all(s == "skipped" for s in delivery_status[1:])  # 未开始的收敛为 skipped


async def test_unknown_receipt_never_resent(tmp_path: Path, patch_provider_builder):
    """unknown（超时可能送达）不自动重发（§6.2/§5.5）。"""
    from tests.fixtures.agent_loop import FiveTurnScenarioClient

    service = await _service(tmp_path)
    service.config.runtime.agent_delivery_enabled = True
    sink = ScriptedSink([DeliveryReceipt(status=DeliveryStatus.UNKNOWN, error_code="timeout")])
    service.bind_delivery_sink(sink)
    client = FiveTurnScenarioClient(protocol="openai")
    patch_provider_builder(lambda provider: client)

    await service.generate_reply(
        group_id=1001, user_id="2002", sender_name="镜子", prompt="K甲赛况如何？",
    )

    assert len(sink.attempts) == 1  # 未重试同一 delivery
    assert len(client.requests) == 1  # 后续生成终止
    with service.store._connect() as conn:
        statuses = [
            row["status"]
            for row in conn.execute("SELECT status FROM agent_deliveries ORDER BY delivery_index")
        ]
    assert statuses[0] == "unknown"
    loop_status = None
    with service.store._connect() as conn:
        loop_status = conn.execute("SELECT status FROM agent_loops").fetchone()["status"]
    assert loop_status == "interrupted"


async def test_middle_chunk_failure_keeps_earlier_facts(tmp_path: Path, patch_provider_builder):
    """中间段失败：已发送事实保留，本轮后续停止。"""
    from tests.fixtures.agent_loop import FiveTurnScenarioClient

    service = await _service(tmp_path)
    for attr, value in [
        ("agent_delivery_enabled", True),
        ("reply_split_threshold_chars", AGENT_LOOP_TEST_SPLIT["threshold"]),
        ("reply_chunk_max_chars", AGENT_LOOP_TEST_SPLIT["chunk_max"]),
    ]:
        setattr(service.config.runtime, attr, value)
    # 前两段成功，第三段失败。
    sink = ScriptedSink([
        DeliveryReceipt(status=DeliveryStatus.SENT, message_id="ok-1"),
        DeliveryReceipt(status=DeliveryStatus.SENT, message_id="ok-2"),
        DeliveryReceipt(status=DeliveryStatus.FAILED, error_code="Boom"),
    ])
    service.bind_delivery_sink(sink)
    client = FiveTurnScenarioClient(protocol="openai")
    patch_provider_builder(lambda provider: client)

    await service.generate_reply(
        group_id=1001, user_id="2002", sender_name="镜子", prompt="K甲赛况如何？",
    )

    assert len(sink.attempts) == 3
    with service.store._connect() as conn:
        sent = conn.execute(
            "SELECT COUNT(*) c FROM agent_deliveries WHERE status='sent'"
        ).fetchone()["c"]
        failed = conn.execute(
            "SELECT COUNT(*) c FROM agent_deliveries WHERE status='failed'"
        ).fetchone()["c"]
        # 首个成功 Chunk 的 qq id 回填兼容列。
        row = conn.execute(
            "SELECT message_id FROM conversation_messages WHERE role='assistant' ORDER BY id LIMIT 1"
        ).fetchone()
    assert sent == 2
    assert failed == 1
    assert row["message_id"] == "ok-1"
    # 前两轮正文 = fixture 前两 Turn。
    assert sink.attempts[0][1][:20] == FIVE_TURN_TEXTS[0][:20]
    assert sink.attempts[1][1][:20] == FIVE_TURN_TEXTS[1][:20]
