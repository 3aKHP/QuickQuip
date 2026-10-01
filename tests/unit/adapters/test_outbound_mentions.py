"""出站提及扫描器与「@名字」解析器单测。

覆盖：数字通道回归、名字最长匹配、歧义/未登记/自指/纯数字名降级、
单条上限、冷却窗降级与恢复、at-all 结构不可达。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from quickquip.adapters.nonebot._llm_reply import (
    _MENTION_COOLDOWN_SECONDS,
    build_llm_reply_message,
    commit_mentions,
    make_mention_resolver,
    mention_cooldown_seconds,
    reset_mention_cooldowns,
    split_outbound_mentions,
)
from quickquip.common.identity import IdentityEntry, IdentityIndex
from quickquip.common.identity_sources import IdentitySnapshot
from tests.fixtures.onebot import DummySegment


class _FakeSegment:
    @staticmethod
    def text(value: str):
        return ("text", value)

    @staticmethod
    def at(qq):
        return ("at", qq)

    @staticmethod
    def reply(message_id):
        return ("reply", message_id)

    @staticmethod
    def image(value: str):
        return ("image", value)


class _FakeMessage(list):
    def __init__(self, segments):
        super().__init__(segments)


@pytest.fixture(autouse=True)
def _clean_cooldowns():
    reset_mention_cooldowns()
    yield
    reset_mention_cooldowns()


def _snapshot(entries, names=None):
    index = IdentityIndex(entries=entries)
    index._build_indexes()
    return IdentitySnapshot(index=index, names=names or {})


def _resolver(snapshot, **kwargs):
    kwargs.setdefault("bot_qq", "999")
    kwargs.setdefault("scope_key", "g1")
    kwargs.setdefault("cooldown_seconds", 600.0)
    return make_mention_resolver(snapshot, **kwargs)


# ── 数字通道回归 ────────────────────────────────────────────────────


def test_digit_channel_converts():
    segments = split_outbound_mentions("@QQ10002 看一下", _FakeMessage, _FakeSegment)
    assert segments == [("at", 10002), ("text", " 看一下")]


def test_digit_channel_rejects_overlong_hallucinated_qq():
    segments = split_outbound_mentions("@QQ1234567890123 长号", _FakeMessage, _FakeSegment)
    assert segments == [("text", "@QQ1234567890123 长号")]


# ── 名字通道 ────────────────────────────────────────────────────────


def test_name_channel_resolves_canonical_and_alias():
    snap = _snapshot([
        IdentityEntry(canonical_name="镜子", qq_ids=["10002"], aliases=["哈基镜"], note=""),
    ])
    resolver = _resolver(snap)
    assert split_outbound_mentions(
        "@镜子 说得对", _FakeMessage, _FakeSegment, resolve_mention=resolver
    ) == [("at", 10002), ("text", " 说得对")]

    reset_mention_cooldowns()
    assert split_outbound_mentions(
        "@哈基镜 说得对", _FakeMessage, _FakeSegment, resolve_mention=resolver
    ) == [("at", 10002), ("text", " 说得对")]


def test_name_channel_longest_match_wins():
    snap = _snapshot([
        IdentityEntry(canonical_name="张三", qq_ids=["10001"], aliases=[], note=""),
        IdentityEntry(canonical_name="张三丰", qq_ids=["10003"], aliases=[], note=""),
    ])
    resolver = _resolver(snap)
    segments = split_outbound_mentions(
        "@张三丰 怎么看", _FakeMessage, _FakeSegment, resolve_mention=resolver
    )
    assert segments == [("at", 10003), ("text", " 怎么看")]


def test_name_channel_observed_card_names_resolve():
    snap = _snapshot([], names={"10007": "小透明"})
    resolver = _resolver(snap)
    segments = split_outbound_mentions(
        "@小透明 在吗", _FakeMessage, _FakeSegment, resolve_mention=resolver
    )
    assert segments == [("at", 10007), ("text", " 在吗")]


def test_unknown_name_stays_text():
    snap = _snapshot([
        IdentityEntry(canonical_name="镜子", qq_ids=["10002"], aliases=[], note=""),
    ])
    resolver = _resolver(snap)
    assert split_outbound_mentions(
        "@路人甲 你好", _FakeMessage, _FakeSegment, resolve_mention=resolver
    ) == [("text", "@路人甲 你好")]


def test_ambiguous_name_stays_text_and_no_shorter_fallback():
    """歧义名字整段保留文本，且不回退到更短的已知名字误艾特他人。"""
    snap = _snapshot(
        [
            IdentityEntry(canonical_name="张三", qq_ids=["10001"], aliases=[], note=""),
            IdentityEntry(canonical_name="老三", qq_ids=["10009"], aliases=["张三"], note=""),
            IdentityEntry(canonical_name="张", qq_ids=["10008"], aliases=[], note=""),
        ],
    )
    resolver = _resolver(snap)
    assert split_outbound_mentions(
        "@张三 人呢", _FakeMessage, _FakeSegment, resolve_mention=resolver
    ) == [("text", "@张三 人呢")]


def test_bot_self_mention_stays_text():
    snap = _snapshot([
        IdentityEntry(canonical_name="机器人", qq_ids=["999"], aliases=[], note=""),
    ])
    resolver = _resolver(snap, bot_qq="999")
    assert split_outbound_mentions(
        "@机器人 你自己呢", _FakeMessage, _FakeSegment, resolve_mention=resolver
    ) == [("text", "@机器人 你自己呢")]


def test_digit_shaped_names_are_not_resolved():
    """纯数字/QQ 数字形态的名字不进入名字通道（防幻觉长号绕过 12 位护栏）。"""
    snap = _snapshot([], names={"10007": "12345"})
    resolver = _resolver(snap)
    assert split_outbound_mentions(
        "@12345 你好", _FakeMessage, _FakeSegment, resolve_mention=resolver
    ) == [("text", "@12345 你好")]


def test_at_all_is_structurally_unreachable():
    """无名为全体成员的成员时保持文本；resolver 只产出快照内 int QQ。"""
    snap = _snapshot([
        IdentityEntry(canonical_name="镜子", qq_ids=["10002"], aliases=[], note=""),
    ])
    resolver = _resolver(snap)
    assert split_outbound_mentions(
        "@全体成员 注意", _FakeMessage, _FakeSegment, resolve_mention=resolver
    ) == [("text", "@全体成员 注意")]


def test_resolver_none_leaves_names_untouched():
    segments = split_outbound_mentions("@镜子 说得对", _FakeMessage, _FakeSegment)
    assert segments == [("text", "@镜子 说得对")]


# ── 护栏：上限与冷却 ────────────────────────────────────────────────


def test_max_mentions_cap_applies_to_both_channels():
    snap = _snapshot([
        IdentityEntry(canonical_name="镜子", qq_ids=["10002"], aliases=[], note=""),
    ])
    resolver = _resolver(snap)
    segments = split_outbound_mentions(
        "@QQ10001 @镜子 @QQ10003 @QQ10004",
        _FakeMessage, _FakeSegment,
        resolve_mention=resolver,
    )
    assert segments == [
        ("at", 10001),
        ("text", " "),
        ("at", 10002),
        ("text", " "),
        ("at", 10003),
        ("text", " @QQ10004"),
    ]


def test_resolve_is_read_only_without_commit():
    """解析侧只读冷却：送达确认前重复解析不互相挤占。"""
    snap = _snapshot([
        IdentityEntry(canonical_name="镜子", qq_ids=["10002"], aliases=[], note=""),
    ])
    resolver = _resolver(snap)
    assert resolver("镜子 你看") == (10002, 2)
    assert resolver("镜子 再看") == (10002, 2)


def test_cooldown_degrades_repeat_mention_within_window():
    snap = _snapshot([
        IdentityEntry(canonical_name="镜子", qq_ids=["10002"], aliases=[], note=""),
    ])
    now = [1000.0]

    def clock():
        return now[0]

    # 送达确认后记账：窗内同一目标降级为文本，出窗恢复
    commit_mentions("g1", [DummySegment.at(10002)], cooldown_seconds=600.0, clock=clock)
    resolver = _resolver(snap, clock=clock)
    assert resolver("镜子 又来") is None
    now[0] += 601
    assert resolver("镜子 恢复") == (10002, 2)


def test_cooldown_is_scoped_per_group_and_target():
    snap = _snapshot([
        IdentityEntry(canonical_name="镜子", qq_ids=["10002"], aliases=[], note=""),
    ])
    commit_mentions("g1", [DummySegment.at(10002)], cooldown_seconds=600.0)
    assert _resolver(snap, scope_key="g1")("镜子") is None
    assert _resolver(snap, scope_key="g2")("镜子") == (10002, 2)  # 另一群不受影响


def test_zero_cooldown_disables_degradation():
    snap = _snapshot([
        IdentityEntry(canonical_name="镜子", qq_ids=["10002"], aliases=[], note=""),
    ])
    commit_mentions("g1", [DummySegment.at(10002)], cooldown_seconds=0.0)
    resolver = _resolver(snap, cooldown_seconds=0.0)
    assert resolver("镜子") == (10002, 2)
    assert resolver("镜子") == (10002, 2)


def test_commit_ignores_non_at_and_malformed_segments():
    commit_mentions("g1", [DummySegment.text("@镜子"), DummySegment("at", {"qq": "abc"})])
    snap = _snapshot([
        IdentityEntry(canonical_name="镜子", qq_ids=["10002"], aliases=[], note=""),
    ])
    assert _resolver(snap)("镜子") == (10002, 2)


# ── mention_cooldown_seconds 配置读取 ────────────────────────────────


def test_mention_cooldown_seconds_reads_runtime_config():
    svc = SimpleNamespace(
        config=SimpleNamespace(runtime=SimpleNamespace(mention_cooldown_seconds=42.0))
    )
    assert mention_cooldown_seconds(svc) == 42.0


def test_mention_cooldown_seconds_falls_back_for_stub_or_invalid():
    assert mention_cooldown_seconds(object()) == _MENTION_COOLDOWN_SECONDS
    bad = SimpleNamespace(
        config=SimpleNamespace(runtime=SimpleNamespace(mention_cooldown_seconds="abc"))
    )
    assert mention_cooldown_seconds(bad) == _MENTION_COOLDOWN_SECONDS


def test_build_llm_reply_message_passes_resolver_through():
    snap = _snapshot([
        IdentityEntry(canonical_name="镜子", qq_ids=["10002"], aliases=[], note=""),
    ])
    resolver = _resolver(snap)
    message = build_llm_reply_message(
        {"reply": "提醒 @镜子 看一下", "images": []},
        _FakeMessage, _FakeSegment,
        resolve_mention=resolver,
    )
    assert list(message) == [("text", "提醒 "), ("at", 10002), ("text", " 看一下")]
