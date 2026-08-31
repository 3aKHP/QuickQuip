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


async def test_health_rejects_non_vision_preprocessor_model(llm_service):
    from tests.fixtures.configs import MIN_LLM_CONFIG_TOML

    config = MIN_LLM_CONFIG_TOML.replace(
        'models = ["gpt-test", "gpt-alt"]',
        'models = ["gpt-test", "gpt-alt"]\nnon_vision_models = ["gpt-test"]',
    )
    llm_service.config_path.write_text(
        config
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

    assert items["image_preprocessing"].status == "warn"
    assert items["image_preprocessing"].details["model_declared_non_vision"] is True
    assert items["image_preprocessing"].details["runtime_bound"] is False


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


async def test_health_verbose_probes_provider_when_reachable(llm_service, monkeypatch):
    """probe_provider=True 且 api_key 已设时，应真实探活并标记 provider_reachable=True。

    覆盖 _probe_provider 薄包装 → provider_health.probe_provider 的接线（重构回归）：
    原先 test_health 只覆盖 key-missing 跳过路径，成功路径未覆盖。
    """
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class _OkClient:
        async def complete(self, request):
            return object()

    monkeypatch.setattr("quickquip.llm.provider.build_provider_client", lambda p: _OkClient())

    report = await llm_service.build_health_report(10001, probe_provider=True)
    items = {item.name: item for item in report.items}
    assert items["provider"].details["provider_reachable"] is True
    assert "probe_latency_ms" in items["provider"].details
    assert items["provider"].status == "ok"


async def test_format_provider_probe_returns_formatted_text(llm_service, monkeypatch):
    """HealthMixin.format_provider_probe 应并发探活并返回格式化文本（/llm probe 接线）。"""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class _OkClient:
        async def complete(self, request):
            return object()

    monkeypatch.setattr("quickquip.llm.provider.build_provider_client", lambda p: _OkClient())

    text = await llm_service.format_provider_probe()
    assert "Provider 探活" in text
    assert "正常" in text  # mock client 成功 → 至少一个 provider ok


async def test_format_current_provider_probe_only_probes_active_model(llm_service, monkeypatch):
    """reload 后验证只探活当前会话的 resolved provider/model，不全量扫 provider。"""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    called: list[tuple[str, str]] = []

    class _CaptureClient:
        def __init__(self, provider_id: str) -> None:
            self.provider_id = provider_id

        async def complete(self, request):
            called.append((self.provider_id, request.model))
            return object()

    monkeypatch.setattr(
        "quickquip.llm.provider.build_provider_client",
        lambda provider: _CaptureClient(provider.id),
    )

    # Add a second configured provider to prove current-probe does not fan out.
    provider = llm_service.config.providers["openai-main"]
    llm_service.config.providers["backup"] = type(provider)(
        id="backup",
        protocol=provider.protocol,
        base_url=provider.base_url,
        api_key_env=provider.api_key_env,
        default_model="backup-model",
        models=["backup-model"],
    )

    text = await llm_service.format_current_provider_probe(10001, chat_type="group")

    assert "Provider 探活（1 个）" in text
    assert called == [("openai-main", "gpt-test")]
    assert "backup" not in text


async def test_format_current_provider_probe_failure_prefaces_config_effective(llm_service, monkeypatch):
    """探活未通过时应前置'配置已生效'，避免 reload 成功但探活 ❌ 被误读为 reload 失败。"""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class _FailClient:
        async def complete(self, request):
            raise RuntimeError("boom")

    monkeypatch.setattr("quickquip.llm.provider.build_provider_client", lambda p: _FailClient())

    text = await llm_service.format_current_provider_probe(10001, chat_type="group")
    assert "配置已生效" in text
    assert "探活未通过" in text
    assert "Provider 探活（1 个）" in text  # body 仍在


# ---------------------------------------------------------------------------
# search 项：SearXNG 需求与 provider 内置搜索覆盖
# ---------------------------------------------------------------------------

async def test_health_search_warns_without_searxng_when_needed(llm_service, monkeypatch):
    """MIN 配置 auto_search 开启（search_web 路径需要 SearXNG），环境缺失 → warn。"""
    monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)

    report = await llm_service.build_health_report(10001)

    items = {item.name: item for item in report.items}
    assert items["search"].status == "warn"
    assert items["search"].summary == "搜索后端未配置"
    assert items["search"].details["builtin_search_covered"] is False


async def test_health_search_ok_with_builtin_search_coverage(tmp_path, monkeypatch):
    """开启 builtin_search 的 gemini provider 存在时：SearXNG 缺失降级 ok。"""
    import textwrap

    from plugins.llm_runtime import LLMService
    from tests.fixtures.configs import write_llm_config_bundle

    config_toml = textwrap.dedent(
        """
        [runtime]
        enabled = true
        default_provider = "gemini-main"
        default_persona = "default"

        [triggers.auto_search]
        enabled = true

        [tools]
        enabled = []

        [[personas]]
        id = "default"
        display_name = "默认人格"
        system_prompt = "你是测试人格。"

        [[providers]]
        id = "gemini-main"
        protocol = "gemini"
        base_url = "https://example.test/v1beta"
        api_key_env = "GEMINI_KEY"
        default_model = "gemini-x"
        models = ["gemini-x"]
        builtin_search = true
        """
    ).strip()
    paths = write_llm_config_bundle(tmp_path, config_toml=config_toml)
    service = LLMService(**paths)
    monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)
    monkeypatch.setenv("GEMINI_KEY", "test-key")

    report = await service.build_health_report(10001)

    items = {item.name: item for item in report.items}
    assert items["search"].status == "ok"
    assert "内置搜索" in items["search"].summary
    assert items["search"].details["builtin_search_covered"] is True
    # 工具列表按生效 provider 过滤：内置搜索会话不暴露 search_web
    assert "search_web" not in items["tools"].details["tools"]


async def test_health_search_ok_when_env_configured(llm_service, monkeypatch):
    monkeypatch.setenv("SEARXNG_BASE_URL", "http://127.0.0.1:8888")

    report = await llm_service.build_health_report(10001)

    items = {item.name: item for item in report.items}
    assert items["search"].status == "ok"
    assert items["search"].summary == "搜索后端已配置"
