"""Integration tests for quickquip.app.message_pipeline.

Covers the resolve_reply dispatch chain: rules take priority over timezone
fallback, rate-limit buckets are set correctly, and the global rule switch
integrates without leaking state between tests.
"""
from __future__ import annotations

import pytest

import quickquip.app.message_pipeline as message_pipeline
from quickquip.games import game_scores as domain_game_scores
from quickquip.app.message_pipeline import (
    build_reply,
    build_timezone_reply,
    detect_kind,
    resolve_reply,
    rule_switch as global_rule_switch,
)


@pytest.fixture(autouse=True)
def _isolate_global_rule_switch():
    saved = dict(global_rule_switch.disabled)
    global_rule_switch.disabled.clear()
    try:
        yield
    finally:
        global_rule_switch.disabled.clear()
        global_rule_switch.disabled.update(saved)


def test_detect_kind_wake_sleep_none():
    assert detect_kind("早安") == "wake"
    assert detect_kind("晚安") == "sleep"
    assert detect_kind("你好") is None


def test_sqlite_stores_are_lazy_proxies():
    assert isinstance(message_pipeline.offline_message_store, message_pipeline._LazyStoreProxy)
    assert isinstance(message_pipeline.group_quote_store, message_pipeline._LazyStoreProxy)


def test_game_scores_uses_domain_singleton():
    assert message_pipeline.game_scores is domain_game_scores


async def test_close_persistent_stores_closes_sqlite_stores(monkeypatch):
    calls: list[str] = []

    class FakeStore:
        def __init__(self, name: str):
            self.name = name

        def close(self) -> None:
            calls.append(self.name)

    monkeypatch.setattr(message_pipeline, "offline_message_store", FakeStore("offline"))
    monkeypatch.setattr(message_pipeline, "group_quote_store", FakeStore("quotes"))

    await message_pipeline.close_persistent_stores()

    assert calls == ["offline", "quotes"]


def test_build_timezone_reply_wake(frozen_now):
    info = build_timezone_reply("早安", sender_name="测试用户", now=frozen_now)
    assert info["rate_limit_key"] == "timezone_wake"
    reply = info["reply"]
    assert "现在是北京时间2026-03-16 09:19" in reply
    assert "@测试用户 " in reply
    assert "要起床了" in reply
    assert "TA也有可能在" in reply


def test_build_timezone_reply_sleep(frozen_now):
    info = build_timezone_reply("晚安", sender_name="测试用户", now=frozen_now)
    assert info["rate_limit_key"] == "timezone_sleep"
    reply = info["reply"]
    assert "@测试用户 " in reply
    assert "要睡觉了" in reply
    assert "TA也有可能在" in reply


async def test_resolve_reply_rule_beats_timezone(frozen_now):
    result = await resolve_reply("神临早安", user_id=1, sender_name="测试用户", now=frozen_now)
    assert result is not None
    assert result["rate_limit_key"] == "divine_arrival"
    assert result["reply"] == "2026-03-16 09:19，@测试用户 区从天降"


async def test_resolve_reply_falls_back_to_timezone(frozen_now):
    result = await resolve_reply("早安", user_id=1, sender_name="测试用户", now=frozen_now)
    assert result is not None
    assert result["rate_limit_key"] == "timezone_wake"
    assert "@测试用户 " in result["reply"]
    assert "要起床了" in result["reply"]


async def test_build_reply_returns_plain_text(frozen_now):
    reply = await build_reply("早安", user_id=1, sender_name="测试用户", now=frozen_now)
    assert reply is not None
    assert "@测试用户 " in reply


async def test_resolve_reply_none_for_unrelated_message(frozen_now):
    assert await resolve_reply("今天天气不错", user_id=1, sender_name="测试用户", now=frozen_now) is None
    assert await build_reply("今天天气不错", user_id=1, sender_name="测试用户", now=frozen_now) is None


async def test_rule_switch_blocks_when_group_id_given(frozen_now):
    global_rule_switch.disable(6001, "divine_arrival")
    blocked = await resolve_reply("神临", user_id=123, sender_name="n", group_id=6001, now=frozen_now)
    assert blocked is None or blocked.get("rule_name") != "divine_arrival"


async def test_rule_switch_not_applied_without_group_id(frozen_now):
    global_rule_switch.disable(6003, "divine_arrival")
    result = await resolve_reply("神临", user_id=123, sender_name="n", now=frozen_now)
    assert result is not None
    assert result["rule_name"] == "divine_arrival"
