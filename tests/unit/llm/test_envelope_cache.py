"""EnvelopeBreakdownCache：record/export 值拷贝与 clear_scope 按会话失效。"""

from __future__ import annotations

from quickquip.llm.envelope_cache import EnvelopeBreakdownCache
from quickquip.llm.epoch import EpochKey


def _key(scope: str, provider: str = "p1", model: str = "m1") -> EpochKey:
    return EpochKey(scope_key=scope, provider_id=provider, model=model)


def test_record_export_returns_value_copy() -> None:
    cache = EnvelopeBreakdownCache(clock=lambda: 100.0)
    cache.record(_key("123456789"), {"time": "现在几点", "vocab": "词表命中"})

    exported = cache.export()
    assert len(exported) == 1
    entry = exported[0]
    assert entry["scope_key"] == "123456789"
    assert entry["provider_id"] == "p1"
    assert entry["total_tokens"] > 0
    assert entry["recorded_at"] == 100.0

    # export 是值拷贝：篡改返回值不影响缓存内部
    parts = entry["parts"]
    assert isinstance(parts, dict)
    parts["time"] = 999999
    breakdown = cache.get(_key("123456789"))
    assert breakdown is not None
    assert breakdown.parts["time"] != 999999


def test_clear_scope_only_drops_that_scope() -> None:
    cache = EnvelopeBreakdownCache()
    cache.record(_key("123456789"), {"time": "a"})
    cache.record(_key("123456789", provider="p2"), {"time": "b"})
    cache.record(_key("private:987654321"), {"time": "c"})

    cache.clear_scope("123456789")

    assert cache.get(_key("123456789")) is None
    assert cache.get(_key("123456789", provider="p2")) is None
    assert cache.get(_key("private:987654321")) is not None
    assert [entry["scope_key"] for entry in cache.export()] == ["private:987654321"]
