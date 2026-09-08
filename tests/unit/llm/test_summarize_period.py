from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from quickquip.llm.config import LLMConfig, PersonaConfig, ProviderConfig, RuntimeConfig
from quickquip.llm.provider import LLMResponse
from quickquip.llm.summarize import generate_period_report


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


class _StubClient:
    def __init__(self, response: LLMResponse):
        self.response = response
        self.requests: list = []

    async def complete(self, request):
        self.requests.append(request)
        return self.response


def _llm_config() -> LLMConfig:
    provider_a = ProviderConfig(
        id="a", protocol="openai", base_url="https://example.test/v1",
        api_key_env="A_KEY", default_model="m1", models=["m1"],
    )
    provider_b = ProviderConfig(
        id="b", protocol="openai", base_url="https://example.test/v1",
        api_key_env="B_KEY", default_model="m2", models=["m2"],
    )
    return LLMConfig(
        runtime=RuntimeConfig(default_provider="a", default_persona="default"),
        providers={"a": provider_a, "b": provider_b},
        personas={"default": PersonaConfig(id="default", display_name="默认", system_prompt="你是测试人格。")},
    )


def _sample_messages(n: int = 5) -> list[dict]:
    return [{"ts": 1600000000.0 + i * 3600, "sender": f"u{i}", "text": f"消息{i}"} for i in range(n)]


@pytest.mark.asyncio
async def test_period_report_success_first_provider(monkeypatch):
    """首个 provider 正常返回 stop 时直接采用。"""
    stub = _StubClient(LLMResponse(text="这是一份周报", model="m1", finish_reason="stop"))

    def _builder(provider):
        return stub

    monkeypatch.setattr("quickquip.llm.summarize.build_provider_client", _builder)

    content, model_used = await generate_period_report(
        _sample_messages(),
        PersonaConfig(id="default", display_name="默认", system_prompt="你是测试人格。"),
        "10001",
        period_label="2026 年第 24 周",
        period_kind="weekly",
        name_table={},
        length_hint=2000,
        model_cascade=["a/m1"],
        llm_config=_llm_config(),
        default_provider_id="a",
        default_model="m1",
        local_tz=LOCAL_TZ,
    )

    assert content == "这是一份周报"
    assert model_used == "a/m1"
    # period report 输出 token 上限应为 8192（日报为 16384）
    assert stub.requests[0].max_output_tokens == 8192


@pytest.mark.asyncio
async def test_period_report_usage_scope_carries_persona(monkeypatch):
    calls: list[tuple] = []

    def _record(feature, **kwargs):
        calls.append((feature, kwargs))

    monkeypatch.setattr("quickquip.llm.summarize.set_usage_scope", _record)
    monkeypatch.setattr(
        "quickquip.llm.summarize.build_provider_client",
        lambda provider: _StubClient(LLMResponse(text="周报", model="m1", finish_reason="stop")),
    )

    await generate_period_report(
        _sample_messages(),
        PersonaConfig(id="archivist", display_name="档案员", system_prompt="你是测试人格。"),
        "10001",
        period_label="2026 年第 24 周",
        period_kind="weekly",
        name_table={},
        length_hint=2000,
        model_cascade=["a/m1"],
        llm_config=_llm_config(),
        default_provider_id="a",
        default_model="m1",
        local_tz=LOCAL_TZ,
    )

    assert ("period_report", {"group_id": "10001", "persona_id": "archivist"}) in calls


@pytest.mark.asyncio
async def test_daily_summary_usage_scope_carries_persona(monkeypatch):
    from quickquip.llm.config import DailySummaryConfig
    from quickquip.llm.summarize import generate_daily_summary

    calls: list[tuple] = []

    def _record(feature, **kwargs):
        calls.append((feature, kwargs))

    monkeypatch.setattr("quickquip.llm.summarize.set_usage_scope", _record)
    monkeypatch.setattr(
        "quickquip.llm.summarize.build_provider_client",
        lambda provider: _StubClient(LLMResponse(text="日报", model="m1", finish_reason="stop")),
    )

    await generate_daily_summary(
        _sample_messages(),
        PersonaConfig(id="archivist", display_name="档案员", system_prompt="你是测试人格。"),
        "10001",
        date_label="2026-06-14",
        name_table={},
        summary_config=DailySummaryConfig(),
        llm_config=_llm_config(),
        default_provider_id="a",
        default_model="m1",
        local_tz=LOCAL_TZ,
    )

    assert ("summary", {"group_id": "10001", "persona_id": "archivist"}) in calls


@pytest.mark.asyncio
async def test_period_report_cascade_on_provider_error(monkeypatch):
    """首个 provider 抛错时应级联到下一个。"""
    class _FailingClient:
        async def complete(self, request):
            from quickquip.llm.provider import LLMProviderError
            raise LLMProviderError("service unavailable")

    stub = _StubClient(LLMResponse(text="备用周报", model="m2", finish_reason="stop"))

    def _builder(provider):
        return _FailingClient() if provider.id == "a" else stub

    monkeypatch.setattr("quickquip.llm.summarize.build_provider_client", _builder)

    content, model_used = await generate_period_report(
        _sample_messages(),
        PersonaConfig(id="default", display_name="默认", system_prompt="你是测试人格。"),
        "10001",
        period_label="2026 年第 24 周",
        period_kind="weekly",
        name_table={},
        length_hint=2000,
        model_cascade=["a/m1", "b/m2"],
        llm_config=_llm_config(),
        default_provider_id="a",
        default_model="m1",
        local_tz=LOCAL_TZ,
    )

    assert content == "备用周报"
    assert model_used == "b/m2"


@pytest.mark.asyncio
async def test_period_report_cascade_on_non_normal_finish(monkeypatch):
    """首个 provider 返回非正常 finish_reason（如 SAFETY）时应级联。"""
    stubs = {
        "a": _StubClient(LLMResponse(text="残稿", model="m1", finish_reason="SAFETY")),
        "b": _StubClient(LLMResponse(text="完整周报", model="m2", finish_reason="stop")),
    }

    def _builder(provider):
        return stubs[provider.id]

    monkeypatch.setattr("quickquip.llm.summarize.build_provider_client", _builder)

    content, model_used = await generate_period_report(
        _sample_messages(),
        PersonaConfig(id="default", display_name="默认", system_prompt="你是测试人格。"),
        "10001",
        period_label="2026 年第 24 周",
        period_kind="weekly",
        name_table={},
        length_hint=2000,
        model_cascade=["a/m1", "b/m2"],
        llm_config=_llm_config(),
        default_provider_id="a",
        default_model="m1",
        local_tz=LOCAL_TZ,
    )

    assert content == "完整周报"
    assert model_used == "b/m2"


@pytest.mark.asyncio
async def test_period_report_all_fail_raises(monkeypatch):
    """所有 provider 都失败时应抛 RuntimeError。"""
    class _FailingClient:
        async def complete(self, request):
            from quickquip.llm.provider import LLMProviderError
            raise LLMProviderError("down")

    monkeypatch.setattr("quickquip.llm.summarize.build_provider_client", lambda p: _FailingClient())

    with pytest.raises(RuntimeError, match="所有模型均调用失败"):
        await generate_period_report(
            _sample_messages(),
            PersonaConfig(id="default", display_name="默认", system_prompt="你是测试人格。"),
            "10001",
            period_label="2026 年第 24 周",
            period_kind="weekly",
            name_table={},
            length_hint=2000,
            model_cascade=["a/m1", "b/m2"],
            llm_config=_llm_config(),
            default_provider_id="a",
            default_model="m1",
            local_tz=LOCAL_TZ,
        )


@pytest.mark.asyncio
async def test_period_report_at_default_placeholder(monkeypatch):
    """cascade 中的 @default 占位符应解析为 default provider/model。"""
    stub = _StubClient(LLMResponse(text="默认周报", model="m1", finish_reason="stop"))

    def _builder(provider):
        return stub

    monkeypatch.setattr("quickquip.llm.summarize.build_provider_client", _builder)

    content, model_used = await generate_period_report(
        _sample_messages(),
        PersonaConfig(id="default", display_name="默认", system_prompt="你是测试人格。"),
        "10001",
        period_label="2026 年 6 月",
        period_kind="monthly",
        name_table={},
        length_hint=2500,
        model_cascade=["@default"],
        llm_config=_llm_config(),
        default_provider_id="a",
        default_model="m1",
        local_tz=LOCAL_TZ,
    )

    assert content == "默认周报"
    assert model_used == "a/m1"


@pytest.mark.asyncio
async def test_period_report_prompt_contains_period_context(monkeypatch):
    """system prompt 和 user content 应包含周期标签与"周报/月报"语境。"""
    stub = _StubClient(LLMResponse(text="ok", model="m1", finish_reason="stop"))
    monkeypatch.setattr("quickquip.llm.summarize.build_provider_client", lambda p: stub)

    await generate_period_report(
        _sample_messages(),
        PersonaConfig(id="default", display_name="默认", system_prompt="你是测试人格。"),
        "10001",
        period_label="2026 年第 24 周",
        period_kind="weekly",
        name_table={},
        length_hint=2000,
        model_cascade=["a/m1"],
        llm_config=_llm_config(),
        default_provider_id="a",
        default_model="m1",
        local_tz=LOCAL_TZ,
    )

    system_prompt = stub.requests[0].system_prompt
    user_content = stub.requests[0].messages[0].content
    assert "周报" in system_prompt
    assert "2026 年第 24 周" in system_prompt
    assert "周报" in user_content
    # 1.15.2 起聊天记录经压缩序列化（分钟块/连发合并），分隔信封不变
    assert "===" in user_content


@pytest.mark.asyncio
async def test_period_report_compact_log_and_format_note(monkeypatch):
    """1.15.2：周/月报输入用压缩序列化（分钟块/连发合并/bot 标记），
    system prompt 附格式说明。"""
    from datetime import datetime

    stub = _StubClient(LLMResponse(text="ok", model="m1", finish_reason="stop"))
    monkeypatch.setattr(
        "quickquip.llm.summarize.build_provider_client", lambda p: stub
    )

    base = datetime(2026, 9, 8, 8, 12, 0, tzinfo=LOCAL_TZ).timestamp()
    messages = [
        {"ts": base, "sender": "张三", "text": "早", "user_id": "1001"},
        {"ts": base + 10, "sender": "张三", "text": "都起了没", "user_id": "1001"},
        {"ts": base + 15, "sender": "QuickQuip", "text": "我来了", "user_id": "999"},
    ]

    await generate_period_report(
        messages,
        PersonaConfig(id="default", display_name="默认", system_prompt="你是测试人格。"),
        "10001",
        period_label="2026 年第 24 周",
        period_kind="weekly",
        name_table={},
        length_hint=2000,
        model_cascade=["a/m1"],
        llm_config=_llm_config(),
        default_provider_id="a",
        default_model="m1",
        local_tz=LOCAL_TZ,
        bot_user_ids=frozenset({"999"}),
    )

    user_content = stub.requests[0].messages[0].content
    assert "[08:12] 张三：早 / 都起了没" in user_content
    assert "QuickQuip(bot)：我来了" in user_content
    assert "【09-08 周二】" in user_content

    system_prompt = stub.requests[0].system_prompt
    assert "聊天记录格式说明" in system_prompt
    assert "×N" in system_prompt
    assert "(bot)" in system_prompt


@pytest.mark.asyncio
async def test_daily_summary_marks_and_caps_bot_lines(monkeypatch):
    """日报中 bot 行带 (bot) 后缀且超长截断；用户行不受影响。"""
    from datetime import datetime

    from quickquip.llm.config import DailySummaryConfig
    from quickquip.llm.summarize import generate_daily_summary, _format_messages

    stub = _StubClient(LLMResponse(text="日报", model="m1", finish_reason="stop"))
    monkeypatch.setattr(
        "quickquip.llm.summarize.build_provider_client", lambda p: stub
    )

    base = datetime(2026, 9, 8, 8, 12, 0, tzinfo=LOCAL_TZ).timestamp()
    messages = [
        {"ts": base, "sender": "张三", "text": "用户原文", "user_id": "1001"},
        {"ts": base + 5, "sender": "QuickQuip", "text": "字" * 500, "user_id": "999"},
    ]

    text = _format_messages(messages, LOCAL_TZ, bot_user_ids={"999"})
    lines = text.splitlines()
    assert lines[0] == "[08:12] 张三：用户原文"
    assert lines[1] == "[08:12] QuickQuip(bot)：" + "字" * 400 + "…"

    # 端到端：bot_user_ids 透传进 user content
    await generate_daily_summary(
        messages,
        PersonaConfig(id="default", display_name="默认", system_prompt="你是测试人格。"),
        "10001",
        date_label="2026-09-08",
        name_table={},
        summary_config=DailySummaryConfig(),
        llm_config=_llm_config(),
        default_provider_id="a",
        default_model="m1",
        local_tz=LOCAL_TZ,
        bot_user_ids={"999"},
    )
    user_content = stub.requests[0].messages[0].content
    assert "QuickQuip(bot)：" in user_content
    assert "字" * 401 not in user_content
