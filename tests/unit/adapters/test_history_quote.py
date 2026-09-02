from __future__ import annotations

import pytest
from types import SimpleNamespace

from quickquip.adapters.nonebot.command_parts import history
from quickquip.adapters.nonebot.command_parts.history import (
    _quote_display_name,
    _resolve_sender_candidates,
    register_history_commands,
)


class _FakeMatch:
    def __init__(self, canonical_name: str):
        self.canonical_name = canonical_name


class _FakeIdentityIndex:
    def __init__(self, by_alias=None, canonical_by_uid=None):
        self.by_alias = by_alias or {}
        self._canonical = canonical_by_uid or {}

    def resolve_user(self, user_id, sender_name=""):
        return _FakeMatch(self._canonical.get(str(user_id), ""))


class _FakeService:
    def __init__(self, index):
        self._index = index
        self.identities = index

    def group_identities(self, group_id):
        return self._index


class _FakeStatsTracker:
    def __init__(self, user_names):
        self._user_names = user_names

    def get_stats(self, group_id):
        return SimpleNamespace(user_names=self._user_names)


class _FakeStore:
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def search_by_sender(self, group_id, *, user_ids=(), name_pattern="", offset=0, limit=50):
        self.calls.append({"user_ids": list(user_ids), "name_pattern": name_pattern})
        return [dict(r) for r in self._rows], len(self._rows)


class _Finished(Exception):
    """模拟 nonebot 的 FinishedException：finish 即终止 handler。"""


class _RecordingMatcher:
    def __init__(self):
        self.handlers = []
        self.sent = []

    def handle(self):
        def deco(fn):
            self.handlers.append(fn)
            return fn

        return deco

    async def finish(self, message):
        self.sent.append(message)
        raise _Finished()


class _FakeMessage(list):
    pass


class _FakeSegment:
    @staticmethod
    def text(value):
        return ("text", value)

    @staticmethod
    def image(value):
        return ("image", value)

    @staticmethod
    def record(value):
        return ("record", value)


class _FakeGroupEvent:
    def __init__(self, text, reply=None):
        self.message_type = "group"
        self.group_id = 100
        self.user_id = 1
        self.self_id = 999
        self.reply = reply
        self._text = text

    def get_message(self):
        return self

    def __str__(self):
        return self._text


def _setup_quote(monkeypatch, *, user_names, index, store):
    """注册命令并替换依赖，返回 quote 的 RecordingMatcher。

    替身 finish 记录输出后抛 _Finished，与真实 nonebot 的
    FinishedException 终止语义一致。
    """
    monkeypatch.setattr(history, "stats_tracker", _FakeStatsTracker(user_names))
    monkeypatch.setattr(history, "get_llm_service", lambda: _FakeService(index))
    monkeypatch.setattr(history, "group_quote_store", store)
    monkeypatch.setattr(history, "_ensure_llm_bindings", lambda: None)

    matchers = {}

    def on_command(name, **kwargs):
        matcher = _RecordingMatcher()
        matchers[name] = matcher
        return matcher

    register_history_commands(on_command, _FakeMessage, _FakeSegment)
    return matchers["quote"]


def _row(**overrides):
    base = {
        "group_seq": 3, "quoted_user_id": "12345",
        "quoted_sender_name": "旧名片", "content": "金句",
    }
    base.update(overrides)
    return base


def test_quote_display_name_prefers_latest_card(monkeypatch):
    monkeypatch.setattr(history, "stats_tracker", _FakeStatsTracker({"u1": "新名片"}))
    svc = _FakeService(_FakeIdentityIndex(canonical_by_uid={"u1": "规范名"}))

    assert _quote_display_name(svc, 100, "u1", "旧名片") == "新名片 (原: 旧名片)"


def test_quote_display_name_unchanged_shows_single_name(monkeypatch):
    monkeypatch.setattr(history, "stats_tracker", _FakeStatsTracker({"u1": "同名"}))
    svc = _FakeService(_FakeIdentityIndex())

    assert _quote_display_name(svc, 100, "u1", "同名") == "同名"


def test_quote_display_name_without_sources_keeps_snapshot(monkeypatch):
    monkeypatch.setattr(history, "stats_tracker", _FakeStatsTracker({}))
    svc = _FakeService(_FakeIdentityIndex())

    assert _quote_display_name(svc, 100, "u1", "快照名") == "快照名"


def test_resolve_sender_candidates_combines_stats_and_alias(monkeypatch):
    monkeypatch.setattr(
        history, "stats_tracker", _FakeStatsTracker({"u1": "阿明", "u2": "别人"}),
    )
    svc = _FakeService(
        _FakeIdentityIndex(by_alias={"阿明": SimpleNamespace(qq_ids=["u1", "u3"])}),
    )

    assert _resolve_sender_candidates(svc, 100, "阿明") == ["u1", "u3"]


def test_resolve_sender_candidates_no_match(monkeypatch):
    monkeypatch.setattr(history, "stats_tracker", _FakeStatsTracker({}))
    svc = _FakeService(_FakeIdentityIndex())

    assert _resolve_sender_candidates(svc, 100, "路人") == []


async def test_quote_by_qq_queries_exact_user_id(monkeypatch):
    store = _FakeStore([_row()])
    matcher = _setup_quote(
        monkeypatch, user_names={"12345": "新名片"}, index=_FakeIdentityIndex(), store=store,
    )

    with pytest.raises(_Finished):
        await matcher.handlers[0](_FakeGroupEvent("quote by 12345"))

    assert store.calls == [{"user_ids": ["12345"], "name_pattern": ""}]
    assert matcher.sent == [
        "👤 「12345」的语录（共 1 条）：\n#3 「金句」—— 新名片 (原: 旧名片)",
    ]


async def test_quote_by_name_resolves_candidates(monkeypatch):
    store = _FakeStore([_row(quoted_user_id="u1", quoted_sender_name="阿明")])
    matcher = _setup_quote(
        monkeypatch,
        user_names={"u1": "阿明"},
        index=_FakeIdentityIndex(by_alias={"阿明": SimpleNamespace(qq_ids=["u1"])}),
        store=store,
    )

    with pytest.raises(_Finished):
        await matcher.handlers[0](_FakeGroupEvent("quote by 阿明"))

    assert store.calls == [{"user_ids": ["u1"], "name_pattern": "阿明"}]
    assert matcher.sent == ["👤 「阿明」的语录（共 1 条）：\n#3 「金句」—— 阿明"]


async def test_quote_by_no_match_reports_miss(monkeypatch):
    store = _FakeStore([])
    matcher = _setup_quote(
        monkeypatch, user_names={}, index=_FakeIdentityIndex(), store=store,
    )

    with pytest.raises(_Finished):
        await matcher.handlers[0](_FakeGroupEvent("quote by 路人"))

    assert matcher.sent == ["未找到「路人」发言的语录"]
