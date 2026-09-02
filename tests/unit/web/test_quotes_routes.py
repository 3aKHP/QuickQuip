from __future__ import annotations

import sys

import pytest

fastapi = pytest.importorskip("fastapi")

import quickquip.app.message_pipeline as message_pipeline  # noqa: E402
from quickquip.app.web.routes import quotes  # noqa: E402


@pytest.fixture(autouse=True)
def _message_pipeline_registered():
    # test_import_isolation 会把 message_pipeline 移出 sys.modules 且不恢复；
    # 缺了它，路由 handler 内的懒导入会重载出全新模块，monkeypatch 的替身失效。
    sys.modules.setdefault("quickquip.app.message_pipeline", message_pipeline)
    yield


class _FakeMatch:
    def __init__(self, canonical_name: str):
        self.canonical_name = canonical_name


class _FakeIdentityIndex:
    def __init__(self, canonical_by_uid=None):
        self._by_uid = canonical_by_uid or {}

    def resolve_user(self, user_id, sender_name=""):
        return _FakeMatch(self._by_uid.get(str(user_id), ""))


class _FakeGroupStats:
    def __init__(self, user_names):
        self.user_names = user_names


class _FakeStatsTracker:
    def __init__(self, user_names):
        self._user_names = user_names

    def get_stats(self, group_id):
        return _FakeGroupStats(self._user_names)


class _FakeStore:
    def __init__(self, rows):
        self._rows = rows

    def list_quotes(self, group_id, offset=0, limit=50, keyword=""):
        return [dict(r) for r in self._rows], len(self._rows)

    def get_by_seq(self, group_id, seq):
        for r in self._rows:
            if r["group_seq"] == seq:
                return dict(r)
        return None


def _row(**overrides):
    base = {
        "id": 1, "group_id": "g1", "quoted_user_id": "u1",
        "quoted_sender_name": "旧名片", "content": "金句",
        "saved_by_user_id": "u2", "saved_at": 1700000000, "group_seq": 1,
    }
    base.update(overrides)
    return base


def _patch_sources(monkeypatch, rows, *, user_names, canonical_by_uid, llm_ok=True):
    # 函数级 import：sys.modules 里的 message_pipeline 可能已被其他测试
    # 驱逐后重载，必须 patch 运行时的当前模块对象，路由懒导入才拿得到替身。
    import quickquip.app.message_pipeline as message_pipeline

    monkeypatch.setattr(message_pipeline, "group_quote_store", _FakeStore(rows))
    identity = _FakeIdentityIndex(canonical_by_uid) if llm_ok else None
    monkeypatch.setattr(
        message_pipeline, "get_sender_identity_sources",
        lambda gid: (user_names or None, identity),
    )


async def test_list_quotes_enriches_sender_display(monkeypatch):
    _patch_sources(
        monkeypatch, [_row()],
        user_names={"u1": "新名片"}, canonical_by_uid={"u1": "规范名"},
    )

    result = await quotes.list_quotes(group_id="g1", offset=0, limit=50, keyword="", request=object())
    entry = result["entries"][0]
    assert entry["sender_display"] == "新名片"
    assert entry["sender_changed"] is True
    assert entry["quoted_sender_name"] == "旧名片"


async def test_list_quotes_falls_back_to_canonical_without_stats(monkeypatch):
    _patch_sources(monkeypatch, [_row()], user_names={}, canonical_by_uid={"u1": "规范名"})

    result = await quotes.list_quotes(group_id="g1", offset=0, limit=50, keyword="", request=object())
    entry = result["entries"][0]
    assert entry["sender_display"] == "规范名"
    assert entry["sender_changed"] is True


async def test_list_quotes_degrades_to_snapshot_when_llm_unavailable(monkeypatch):
    _patch_sources(
        monkeypatch, [_row()],
        user_names={}, canonical_by_uid={}, llm_ok=False,
    )

    result = await quotes.list_quotes(group_id="g1", offset=0, limit=50, keyword="", request=object())
    entry = result["entries"][0]
    assert entry["sender_display"] == "旧名片"
    assert entry["sender_changed"] is False


async def test_by_seq_enriches_single_quote(monkeypatch):
    _patch_sources(monkeypatch, [_row()], user_names={}, canonical_by_uid={"u1": "规范名"})

    q = await quotes.get_by_seq("g1", 1, object())
    assert q["sender_display"] == "规范名"
    assert q["sender_changed"] is True


async def test_list_quotes_falls_back_to_stats_without_llm(monkeypatch):
    _patch_sources(
        monkeypatch, [_row()],
        user_names={"u1": "新名片"}, canonical_by_uid={}, llm_ok=False,
    )

    result = await quotes.list_quotes(group_id="g1", offset=0, limit=50, keyword="", request=object())
    entry = result["entries"][0]
    assert entry["sender_display"] == "新名片"
    assert entry["sender_changed"] is True


def test_get_sender_identity_sources_degrades_when_llm_unavailable(monkeypatch):
    import quickquip.app.message_pipeline as message_pipeline

    monkeypatch.setattr(message_pipeline, "stats_tracker", _FakeStatsTracker({"u1": "名片"}))

    def _boom():
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(message_pipeline, "_ensure_llm_bindings", _boom)

    user_names, identity_index = message_pipeline.get_sender_identity_sources("g1")
    assert user_names == {"u1": "名片"}
    assert identity_index is None
