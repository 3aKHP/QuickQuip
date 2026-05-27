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
    assert items["image_preprocessing"].details["enabled"] is False


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


async def test_health_reports_bound_image_preprocessor(llm_service, monkeypatch):
    from tests.fixtures.configs import MIN_LLM_CONFIG_TOML

    class _StubClient:
        pass

    monkeypatch.setattr("quickquip.llm.service.build_provider_client", lambda provider: _StubClient())
    llm_service.config_path.write_text(
        MIN_LLM_CONFIG_TOML
        + """

[image_preprocessing]
enabled = true
provider_id = "openai-main"
model = "gpt-test"
""",
        encoding="utf-8",
    )
    llm_service.reload_config()

    report = await llm_service.build_health_report(10001)
    items = {item.name: item for item in report.items}

    assert items["image_preprocessing"].status == "ok"
    assert items["image_preprocessing"].details["runtime_bound"] is True


async def test_health_warns_when_image_preprocessor_provider_missing(llm_service):
    from tests.fixtures.configs import MIN_LLM_CONFIG_TOML

    llm_service.config_path.write_text(
        MIN_LLM_CONFIG_TOML
        + """

[image_preprocessing]
enabled = true
provider_id = "missing-provider"
""",
        encoding="utf-8",
    )
    llm_service.reload_config()

    report = await llm_service.build_health_report(10001)
    items = {item.name: item for item in report.items}

    assert items["image_preprocessing"].status == "warn"
    assert items["image_preprocessing"].details["provider_declared"] is False


def test_reload_config_refreshes_sensitive_filter(llm_service, monkeypatch):
    calls = 0

    def _fake_reload():
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr("quickquip.llm.service._reload_sensitive_filter", _fake_reload)

    llm_service.reload_config()

    assert calls == 1


def test_format_health_report_redacts_sensitive_filter_details():
    """`/llm health verbose` posts back into chat. The sensitive_filter
    item's details (counts, etc.) are deployment-time facts that must not
    leak there even with verbose=True. The redaction list in
    format_health_report enforces this."""
    from quickquip.llm.health import (
        HealthCheckItem,
        HealthReport,
        format_health_report,
    )

    report = HealthReport(
        status="ok",
        scope_key="test",
        chat_type="group",
        duration_ms=1.0,
        items=[
            HealthCheckItem(
                name="sensitive_filter",
                status="ok",
                summary="敏感词过滤：已启用",
                details={"loaded": True, "total": 87, "block": 73, "soft": 14},
            ),
            # Control case: a non-redacted item should still expose details.
            HealthCheckItem(
                name="provider",
                status="ok",
                summary="dummy",
                details={"provider_id": "x", "model": "y"},
            ),
        ],
    )

    rendered = format_health_report(report, verbose=True)
    # Counts must NOT appear in the chat-side render.
    assert "87" not in rendered
    assert "73" not in rendered
    assert "14" not in rendered
    assert "total" not in rendered
    assert "block: " not in rendered
    # Summary stays — that's the point.
    assert "敏感词过滤：已启用" in rendered
    # Sanity check: other items are unaffected by the redaction.
    assert "provider_id" in rendered
