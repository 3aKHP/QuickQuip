from __future__ import annotations

import pytest

from quickquip.app.web.action_queue import WebAdminAction
from quickquip.adapters.nonebot import web_admin_actions


@pytest.mark.asyncio
async def test_health_check_action_uses_web_admin_scope(monkeypatch):
    calls: list[tuple[str, str, bool]] = []

    class FakeService:
        async def format_health(self, chat_id, chat_type="group", *, verbose=False):
            calls.append((chat_id, chat_type, verbose))
            return "health text"

    monkeypatch.setattr(web_admin_actions, "_ensure_llm_bindings", lambda: None)
    monkeypatch.setattr(web_admin_actions, "get_llm_service", lambda: FakeService())

    result = await web_admin_actions.execute_web_admin_action(
        WebAdminAction(
            id="h1",
            action_type="health_check",
            payload={"verbose": True, "scope_key": "__web_admin__"},
            status="running",
            created_at="",
            updated_at="",
        )
    )

    assert result == {"ok": True, "text": "health text"}
    assert calls == [("__web_admin__", "group", True)]


@pytest.mark.asyncio
async def test_awakening_reload_action_reloads_config_and_rules(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(web_admin_actions, "_ensure_llm_bindings", lambda: None)
    monkeypatch.setattr(web_admin_actions, "get_llm_service", lambda: object())

    import quickquip.adapters.nonebot.awakening_plugin as awakening_plugin

    def _fake_reload_and_reschedule():
        calls.append("awakening+reschedule")
        return 300

    monkeypatch.setattr(
        awakening_plugin, "reload_awakening_and_reschedule", _fake_reload_and_reschedule
    )
    monkeypatch.setattr(
        web_admin_actions,
        "reload_chat_rules_pipeline",
        lambda: calls.append("rules") or {"rules": 1},
    )

    result = await web_admin_actions.execute_web_admin_action(
        WebAdminAction(
            id="a1",
            action_type="awakening_reload",
            payload={},
            status="running",
            created_at="",
            updated_at="",
        )
    )

    assert result == {"ok": True, "summary": {"rules": 1}, "boredom_scan_interval": 300}
    assert calls == ["awakening+reschedule", "rules"]


@pytest.mark.asyncio
async def test_summary_now_action_uses_public_executor(monkeypatch):
    async def fake_send_daily_summary_now(group_id, bot=None):
        assert group_id == "123456"
        assert bot == "bot"
        return {"model_used": "m", "char_count": 3}

    monkeypatch.setattr(web_admin_actions, "_get_bot", lambda: "bot")
    import quickquip.adapters.nonebot.daily_summary_plugin as summary_plugin

    monkeypatch.setattr(summary_plugin, "send_daily_summary_now", fake_send_daily_summary_now)

    result = await web_admin_actions.execute_web_admin_action(
        WebAdminAction(
            id="s1",
            action_type="summary_now",
            payload={"group_id": "123456"},
            status="running",
            created_at="",
            updated_at="",
        )
    )

    assert result == {"model_used": "m", "char_count": 3}


@pytest.mark.asyncio
async def test_briefing_now_action_uses_public_executor(monkeypatch):
    async def fake_send_daily_briefing_now(group_id, period=None, bot=None):
        assert group_id == "123456"
        assert period == "morning"
        assert bot == "bot"
        return {"period": "morning", "model_used": "m", "char_count": 3}

    monkeypatch.setattr(web_admin_actions, "_get_bot", lambda: "bot")
    import quickquip.adapters.nonebot.daily_briefing_plugin as briefing_plugin

    monkeypatch.setattr(briefing_plugin, "send_daily_briefing_now", fake_send_daily_briefing_now)

    result = await web_admin_actions.execute_web_admin_action(
        WebAdminAction(
            id="b1",
            action_type="briefing_now",
            payload={"group_id": "123456", "period": "morning"},
            status="running",
            created_at="",
            updated_at="",
        )
    )

    assert result == {"period": "morning", "model_used": "m", "char_count": 3}


@pytest.mark.asyncio
async def test_period_report_now_action_uses_public_executor(monkeypatch):
    calls: list[tuple] = []

    async def fake_send_period_report_now(group_id, period_type, bot=None, before_generate=None):
        calls.append((group_id, period_type, bot))
        return {"model_used": "m", "char_count": 5}

    monkeypatch.setattr(web_admin_actions, "_get_bot", lambda: "bot")
    import quickquip.adapters.nonebot.daily_summary_plugin as summary_plugin

    monkeypatch.setattr(summary_plugin, "send_period_report_now", fake_send_period_report_now)

    result = await web_admin_actions.execute_web_admin_action(
        WebAdminAction(
            id="p1",
            action_type="period_report_now",
            payload={"group_id": "123456", "period_type": "weekly"},
            status="running",
            created_at="",
            updated_at="",
        )
    )

    assert result == {"model_used": "m", "char_count": 5}
    assert calls == [("123456", "weekly", "bot")]


@pytest.mark.asyncio
async def test_epoch_snapshot_action_exports_state(monkeypatch, tmp_path):
    from quickquip.llm.epoch import EpochKey, EpochManager, EpochParams
    from quickquip.llm.envelope_cache import EnvelopeBreakdownCache
    from quickquip.llm.store import LLMStore
    from quickquip.llm.token_estimate import estimate_tokens

    store = LLMStore(tmp_path / "snap.db")
    store.append_conversation_message("123456789", "u1", "user", "问一句")
    store.append_conversation_message("123456789", None, "assistant", "答一句")

    class FakeConfig:
        providers = {}

        def resolve_epoch_params(self, provider=None):
            return EpochParams()

    class FakeSettings:
        history_limit = 200

    class FakeService:
        pass

    svc = FakeService()
    svc.store = store
    svc.config = FakeConfig()
    svc.get_chat_settings = lambda chat_id, chat_type="group": FakeSettings()
    svc._epochs = EpochManager(clock=lambda: 1_000.0)
    svc._envelope_cache = EnvelopeBreakdownCache(clock=lambda: 1_000.0)
    key = EpochKey(scope_key="123456789", provider_id="p1", model="m1")
    svc._epochs.maybe_advance(key, store=store, params=EpochParams(context_tokens=10))
    svc._envelope_cache.record(key, {"time": "【轮次上下文】", "memories": "记忆一条"})

    monkeypatch.setattr(web_admin_actions, "_ensure_llm_bindings", lambda: None)
    monkeypatch.setattr(web_admin_actions, "get_llm_service", lambda: svc)

    result = await web_admin_actions.execute_web_admin_action(
        WebAdminAction(
            id="e1",
            action_type="epoch_snapshot",
            payload={},
            status="running",
            created_at="",
            updated_at="",
        )
    )

    assert isinstance(result["generated_at"], float)
    entry = result["keys"][0]
    assert entry["scope_key"] == "123456789"
    assert entry["provider_id"] == "p1"
    assert entry["anchor_id"] >= 0
    assert entry["window_rows"] == 2
    assert entry["window_tokens"] > 0
    assert entry["history_limit"] == 200
    assert entry["params"]["cap_tokens"] == EpochParams().cap_tokens
    envelope = result["envelopes"][0]
    assert envelope["recorded_at"] == 1_000.0
    assert envelope["parts"]["time"] == estimate_tokens("【轮次上下文】")
    assert envelope["total_tokens"] == sum(envelope["parts"].values())
