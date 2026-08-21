from __future__ import annotations

import contextlib
import types
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from quickquip.adapters.nonebot import daily_briefing_plugin
from quickquip.chat.daily_briefing import default_period_for_now


@pytest.mark.asyncio
async def test_send_daily_briefing_now_reuses_renderer(monkeypatch):
    rendered: list[tuple[str, str]] = []

    async def fake_render(group_id, period):
        rendered.append((group_id, period))
        return "briefing text", "model-a"

    sent: list[tuple[int, str]] = []
    async def fake_send_group_msg(group_id, message):
        sent.append((group_id, message))

    class FakeBot:
        send_group_msg = staticmethod(fake_send_group_msg)

    bot = FakeBot()
    monkeypatch.setattr(daily_briefing_plugin, "_is_group_enabled", lambda group_id: group_id == "123456")
    monkeypatch.setattr(daily_briefing_plugin, "_on_cooldown", lambda group_id: False)
    monkeypatch.setattr(daily_briefing_plugin, "_mark_triggered", lambda group_id: None)
    monkeypatch.setattr(daily_briefing_plugin, "_render_briefing", fake_render)
    before_generate_calls: list[str] = []

    async def before_generate(period):
        before_generate_calls.append(period)

    result = await daily_briefing_plugin.send_daily_briefing_now("123456", "noon", bot, before_generate)

    assert result == {"period": "noon", "model_used": "model-a", "char_count": len("briefing text")}
    assert rendered == [("123456", "noon")]
    assert sent == [(123456, "briefing text")]
    assert before_generate_calls == ["noon"]


# ── characterization: v1.12.1 生成编排下沉前的行为钉住 ──────────────────

LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def _fixed_datetime(hour, minute=0):
    class _Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            current = cls(2026, 5, 4, hour, minute, tzinfo=LOCAL_TZ)
            return current if tz is None else current.astimezone(tz)

    return _Fixed


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (0, "morning"),
        (10, "morning"),
        (11, "noon"),    # 边界：11:00 起算午报
        (17, "noon"),
        (18, "evening"),  # 边界：18:00 起算晚报
        (23, "evening"),
    ],
)
def test_default_period_for_now_boundaries(hour, expected):
    """钉住：时段划分 [0,11)=morning，[11,18)=noon，[18,24)=evening。"""
    now = datetime(2026, 5, 4, hour, 0, tzinfo=LOCAL_TZ)
    assert default_period_for_now(now) == expected


def _patch_render_deps(monkeypatch, *, message_count=10, min_for_llm=5,
                       load_error=False, personas=None, persona_id="p1"):
    """打桩 _render_briefing 的决策依赖，返回捕获字典。"""
    captured: dict = {"llm_calls": []}

    if personas is None:
        personas = {"p1": object()}

    fake_svc = types.SimpleNamespace(
        config=types.SimpleNamespace(
            daily_briefing=types.SimpleNamespace(min_messages_for_llm=min_for_llm),
            load_error=load_error,
            personas=personas,
        ),
        get_group_settings=lambda gid: types.SimpleNamespace(
            persona_id=persona_id, provider_id="prov-1", model="model-1",
        ),
    )

    async def fake_build_context(**kw):
        return types.SimpleNamespace(message_count=message_count)

    async def fake_generate(**kw):
        captured["llm_calls"].append(kw)
        return ("LLM 播报", "model-1")

    monkeypatch.setattr(daily_briefing_plugin, "_ensure_llm_bindings", lambda: None)
    monkeypatch.setattr(daily_briefing_plugin, "get_llm_service", lambda: fake_svc)
    monkeypatch.setattr(daily_briefing_plugin, "build_briefing_context", fake_build_context)
    monkeypatch.setattr(
        daily_briefing_plugin, "build_fallback_briefing", lambda ctx: "FALLBACK",
    )
    monkeypatch.setattr(daily_briefing_plugin, "generate_daily_briefing", fake_generate)
    return captured


@pytest.mark.asyncio
async def test_render_briefing_returns_llm_content_on_success(monkeypatch):
    """钉住：正常路径返回 LLM 生成结果。"""
    captured = _patch_render_deps(monkeypatch)

    result = await daily_briefing_plugin._render_briefing("10001", "morning")

    assert result == ("LLM 播报", "model-1")
    assert len(captured["llm_calls"]) == 1
    assert captured["llm_calls"][0]["group_id"] == "10001"


@pytest.mark.asyncio
async def test_render_briefing_fallback_when_config_load_error(monkeypatch):
    """钉住：config.load_error 为真时直接回退，不调用 LLM。"""
    captured = _patch_render_deps(monkeypatch, load_error=True)

    result = await daily_briefing_plugin._render_briefing("10001", "morning")

    assert result == ("FALLBACK", "fallback")
    assert captured["llm_calls"] == []


@pytest.mark.asyncio
async def test_render_briefing_fallback_when_no_persona(monkeypatch):
    """钉住：personas 为空表时回退，不调用 LLM。"""
    captured = _patch_render_deps(monkeypatch, personas={})

    result = await daily_briefing_plugin._render_briefing("10001", "morning")

    assert result == ("FALLBACK", "fallback")
    assert captured["llm_calls"] == []


@pytest.mark.asyncio
async def test_render_briefing_falls_back_to_first_persona(monkeypatch):
    """钉住：群 persona_id 不在 personas 表时回退到字典里第一个 persona。"""
    first, second = object(), object()
    captured = _patch_render_deps(
        monkeypatch, personas={"a": first, "b": second}, persona_id="missing",
    )

    result = await daily_briefing_plugin._render_briefing("10001", "morning")

    assert result == ("LLM 播报", "model-1")
    assert captured["llm_calls"][0]["persona"] is first


@pytest.mark.asyncio
async def test_render_briefing_fallback_below_min_messages_for_llm(monkeypatch):
    """钉住：message_count < min_messages_for_llm 时回退（边界：恰好等于则走 LLM）。"""
    captured = _patch_render_deps(monkeypatch, message_count=4, min_for_llm=5)

    result = await daily_briefing_plugin._render_briefing("10001", "noon")

    assert result == ("FALLBACK", "fallback")
    assert captured["llm_calls"] == []

    captured = _patch_render_deps(monkeypatch, message_count=5, min_for_llm=5)
    result = await daily_briefing_plugin._render_briefing("10001", "noon")

    assert result == ("LLM 播报", "model-1")
    assert len(captured["llm_calls"]) == 1


@pytest.mark.asyncio
async def test_render_briefing_fallback_when_llm_raises(monkeypatch):
    """钉住：LLM 抛异常时回退到 fallback 文案（不外抛）。"""
    _patch_render_deps(monkeypatch)

    async def boom(**kw):
        raise RuntimeError("llm down")

    monkeypatch.setattr(daily_briefing_plugin, "generate_daily_briefing", boom)

    result = await daily_briefing_plugin._render_briefing("10001", "evening")

    assert result == ("FALLBACK", "fallback")


@pytest.mark.asyncio
async def test_send_one_skips_when_rule_switch_disabled(monkeypatch):
    """钉住：rule_switch 关闭时 _send_one 不渲染、不发送。"""
    rendered: list = []
    sent: list = []

    async def fake_render(group_id, period):
        rendered.append(group_id)
        return ("text", "model-a")

    bot = types.SimpleNamespace(
        send_group_msg=lambda group_id, message: sent.append(group_id),
    )
    monkeypatch.setattr(
        daily_briefing_plugin, "rule_switch",
        types.SimpleNamespace(is_enabled=lambda gid, name: False),
    )
    monkeypatch.setattr(daily_briefing_plugin, "_render_briefing", fake_render)

    await daily_briefing_plugin._send_one(bot, "10001", "morning")

    assert rendered == []
    assert sent == []


@pytest.mark.asyncio
async def test_send_one_swallows_send_failure(monkeypatch):
    """钉住：发送异常被吞掉，不外抛。"""
    async def fake_render(group_id, period):
        return ("text", "model-a")

    async def failing_send(group_id, message):
        raise RuntimeError("network down")

    bot = types.SimpleNamespace(send_group_msg=failing_send)
    monkeypatch.setattr(
        daily_briefing_plugin, "rule_switch",
        types.SimpleNamespace(is_enabled=lambda gid, name: True),
    )
    monkeypatch.setattr(daily_briefing_plugin, "_render_briefing", fake_render)
    monkeypatch.setattr(
        daily_briefing_plugin, "bot_action_trace",
        lambda **kw: contextlib.nullcontext(),
    )

    await daily_briefing_plugin._send_one(bot, "10001", "morning")


@pytest.mark.asyncio
async def test_send_daily_briefing_now_rejects_invalid_period(monkeypatch):
    """钉住：非法 period 抛 ValueError（在启用/冷却检查之前）。"""
    with pytest.raises(ValueError, match="period must be morning, noon, or evening"):
        await daily_briefing_plugin.send_daily_briefing_now(
            "123456", "midnight", types.SimpleNamespace(),
        )


@pytest.mark.asyncio
async def test_send_daily_briefing_now_normalizes_chinese_alias(monkeypatch):
    """钉住：中文别名"早报"归一化为 morning。"""
    rendered: list[tuple[str, str]] = []

    async def fake_render(group_id, period):
        rendered.append((group_id, period))
        return ("text", "model-a")

    async def fake_send_msg(group_id, message):
        return None

    bot = types.SimpleNamespace(send_group_msg=fake_send_msg)
    monkeypatch.setattr(daily_briefing_plugin, "_is_group_enabled", lambda gid: True)
    monkeypatch.setattr(daily_briefing_plugin, "_on_cooldown", lambda gid: False)
    monkeypatch.setattr(daily_briefing_plugin, "_mark_triggered", lambda gid: None)
    monkeypatch.setattr(daily_briefing_plugin, "_render_briefing", fake_render)

    result = await daily_briefing_plugin.send_daily_briefing_now(
        "123456", "早报", bot,
    )

    assert result["period"] == "morning"
    assert rendered == [("123456", "morning")]


@pytest.mark.asyncio
async def test_send_daily_briefing_now_defaults_period_by_current_hour(monkeypatch):
    """钉住：未指定 period 时按当前时刻选时段（15:30 → noon）。"""
    rendered: list[tuple[str, str]] = []

    async def fake_render(group_id, period):
        rendered.append((group_id, period))
        return ("text", "model-a")

    async def fake_send_msg(group_id, message):
        return None

    bot = types.SimpleNamespace(send_group_msg=fake_send_msg)
    monkeypatch.setattr(daily_briefing_plugin, "datetime", _fixed_datetime(15, 30))
    monkeypatch.setattr(daily_briefing_plugin, "_is_group_enabled", lambda gid: True)
    monkeypatch.setattr(daily_briefing_plugin, "_on_cooldown", lambda gid: False)
    monkeypatch.setattr(daily_briefing_plugin, "_mark_triggered", lambda gid: None)
    monkeypatch.setattr(daily_briefing_plugin, "_render_briefing", fake_render)

    result = await daily_briefing_plugin.send_daily_briefing_now("123456", None, bot)

    assert result["period"] == "noon"
    assert rendered == [("123456", "noon")]


@pytest.mark.asyncio
async def test_send_daily_briefing_now_error_messages_exact(monkeypatch):
    """钉住裸 RuntimeError 消息文本。"""
    monkeypatch.setattr(daily_briefing_plugin, "_is_group_enabled", lambda gid: False)
    with pytest.raises(RuntimeError) as exc_info:
        await daily_briefing_plugin.send_daily_briefing_now(
            "123456", "noon", types.SimpleNamespace(),
        )
    assert str(exc_info.value) == "daily briefing is not enabled for this group"

    monkeypatch.setattr(daily_briefing_plugin, "_is_group_enabled", lambda gid: True)
    monkeypatch.setattr(daily_briefing_plugin, "_on_cooldown", lambda gid: True)
    with pytest.raises(RuntimeError) as exc_info:
        await daily_briefing_plugin.send_daily_briefing_now(
            "123456", "noon", types.SimpleNamespace(),
        )
    assert str(exc_info.value) == "briefing generation is on cooldown"


@pytest.mark.asyncio
async def test_job_send_period_filters_by_rule_switch_and_isolates_failures(monkeypatch):
    """钉住：发送 job 只发 rule_switch 启用的群；单群失败不影响他群。"""
    attempted: list[str] = []

    async def fake_send_one(bot, group_id, period):
        attempted.append(group_id)
        if group_id == "10001":
            raise RuntimeError("boom")

    bot = types.SimpleNamespace(name="fake-bot")
    monkeypatch.setattr(
        daily_briefing_plugin, "nonebot",
        types.SimpleNamespace(get_bot=lambda: bot),
    )
    monkeypatch.setattr(
        daily_briefing_plugin, "daily_briefing_enabled_groups",
        types.SimpleNamespace(all_groups=lambda: ["10001", "10002", "10003"]),
    )
    monkeypatch.setattr(
        daily_briefing_plugin, "rule_switch",
        types.SimpleNamespace(is_enabled=lambda gid, name: gid != "10003"),
    )
    monkeypatch.setattr(daily_briefing_plugin, "_send_one", fake_send_one)

    await daily_briefing_plugin._job_send_period("morning")

    assert sorted(attempted) == ["10001", "10002"]


@pytest.mark.asyncio
async def test_job_send_period_noop_without_bot(monkeypatch):
    """钉住：nonebot 不可用（None）时 job 直接返回。"""
    monkeypatch.setattr(daily_briefing_plugin, "nonebot", None)

    async def fake_send_one(bot, group_id, period):
        raise AssertionError("should not be called")

    monkeypatch.setattr(daily_briefing_plugin, "_send_one", fake_send_one)

    await daily_briefing_plugin._job_send_period("morning")
