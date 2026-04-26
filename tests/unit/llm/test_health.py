from __future__ import annotations

import json

from quickquip.llm.tools import LLMToolCall, ToolExecutionContext


async def test_health_report_checks_core_layers(llm_service, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    report = await llm_service.build_health_report(10001)

    assert report.scope_key == "10001"
    assert report.chat_type == "group"
    assert report.status in {"ok", "warn"}

    items = {item.name: item for item in report.items}
    assert items["llm_config"].status == "ok"
    assert items["provider"].details["api_key_status"] == "set"
    assert "provider_reachable" not in items["provider"].details  # no probe by default
    assert items["database"].status == "ok"
    assert "get_health_status" in items["tools"].details["tools"]


async def test_format_health_is_group_safe(llm_service, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    text = await llm_service.format_health(10001, verbose=True)

    assert "LLM 健康检查" in text
    assert "provider" in text
    assert "api_key_status: missing" in text
    assert "test-key" not in text


async def test_health_verbose_skips_probe_when_key_missing(llm_service, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    report = await llm_service.build_health_report(10001, probe_provider=True)

    items = {item.name: item for item in report.items}
    # key missing → probe is skipped, no provider_reachable field
    assert "provider_reachable" not in items["provider"].details


async def test_health_tool_returns_formatted_report(llm_service, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    context = ToolExecutionContext(
        group_id=10001,
        user_id=20002,
        sender_name="tester",
        provider_id="openai-main",
        model="gpt-test",
        chat_scope="10001",
    )
    result = await llm_service.tool_registry.execute(
        LLMToolCall(
            id="call_1",
            name="get_health_status",
            arguments_json=json.dumps({"verbose": False}),
        ),
        context,
    )

    assert result.is_error is False
    assert "LLM 健康检查" in result.content
    assert "provider" in result.content
