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


async def test_no_record_fallback_keeps_reply_when_delivery_enabled(
    tmp_path: Path, patch_provider_builder
):
    """同 scope 已有未关闭 Loop（并发触发）时退回无记录路径：reply 必须保留。

    无记录路径没有 sink 交付，最终正文只能靠 reply 单次发送；逐 Turn 开关
    不得在这条路径上把 reply 置空（2026-09-07 生产回归：同群并发触发的第二
    条回复被静默吞掉）。
    """
    from quickquip.llm.agent_records import TriggerKind
    from quickquip.llm.store_parts.agent_records import UserTriggerPayload
    from tests.fixtures.agent_loop import CollectingSink, FiveTurnScenarioClient

    service = await _service(tmp_path)
    service.config.runtime.agent_delivery_enabled = True
    sink = CollectingSink()
    service.bind_delivery_sink(sink)
    client = FiveTurnScenarioClient(protocol="openai")
    patch_provider_builder(lambda provider: client)
    # 模拟同群另一条触发仍在跑：scope 1001 上留一个未关闭 Loop。
    generation, _ = service.store.agent_scope_state("1001")
    service.store.begin_loop(
        "1001", generation, TriggerKind.GROUP_DIRECT,
        UserTriggerPayload(user_id="3003", sender_name="先手", content="先来的那条"),
    )

    result = await service.generate_reply(
        group_id=1001, user_id="2002", sender_name="镜子", prompt="K甲赛况如何？",
    )

    assert len(client.requests) == 5  # 完整跑完五 Turn
    assert sink.deliveries == []  # 无记录路径不经 sink
    assert result["reply"] == FIVE_TURN_TEXTS[4]
    with service.store._connect() as conn:
        loop_count = conn.execute("SELECT COUNT(*) FROM agent_loops").fetchone()[0]
    assert loop_count == 1  # 只有占位 Loop，本轮未建新 Loop


async def test_no_record_fallback_surfaces_abort_when_delivery_enabled(
    tmp_path: Path, patch_provider_builder, monkeypatch
):
    """无记录路径上逐轮预算门禁触发 DeliveryAborted：必须给出可见提示而非空串。

    门禁不依赖 recorder，所以并发退化的那轮同样可能中途超限；该轮没有任何
    sink 交付，若沿逐 Turn 模式静默处理，用户什么都收不到。
    """
    import quickquip.llm.service as service_module
    from quickquip.llm.agent_records import TriggerKind
    from quickquip.llm.request_budget import RequestBudgetExceeded
    from quickquip.llm.store_parts.agent_records import UserTriggerPayload
    from tests.fixtures.agent_loop import CollectingSink, FiveTurnScenarioClient

    service = await _service(tmp_path)
    service.config.runtime.agent_delivery_enabled = True
    sink = CollectingSink()
    service.bind_delivery_sink(sink)
    client = FiveTurnScenarioClient(protocol="openai")
    patch_provider_builder(lambda provider: client)
    generation, _ = service.store.agent_scope_state("1001")
    service.store.begin_loop(
        "1001", generation, TriggerKind.GROUP_DIRECT,
        UserTriggerPayload(user_id="3003", sender_name="先手", content="先来的那条"),
    )
    # 预检与逐轮门禁共用 enforce_request_budget：前两次放行（预检 + 第一轮），
    # 第三次（工具结果撑大请求后的第二轮）超限。
    calls = {"n": 0}

    def _budget(config, provider, request):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise RequestBudgetExceeded("input 9999 > budget 1")

    monkeypatch.setattr(service_module, "enforce_request_budget", _budget)

    result = await service.generate_reply(
        group_id=1001, user_id="2002", sender_name="镜子", prompt="K甲赛况如何？",
    )

    assert len(client.requests) == 1  # 第二轮被门禁拦下
    assert sink.deliveries == []
    assert result["reply"] == "本次回复未确认送达，已停止后续生成。"
