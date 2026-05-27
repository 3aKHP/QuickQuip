from __future__ import annotations

import pytest

from quickquip.adapters.nonebot import daily_briefing_plugin


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
