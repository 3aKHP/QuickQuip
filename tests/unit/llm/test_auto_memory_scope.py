"""Auto-memory usage attribution tests (#109-A)."""

from __future__ import annotations

from quickquip.llm.service_parts.auto_memory import AutoMemoryMixin


class _Host(AutoMemoryMixin):
    def __init__(self) -> None:
        self._init_auto_memory()


async def test_auto_memory_scope_carries_explicit_persona(monkeypatch):
    import quickquip.llm.service_parts.auto_memory as auto_memory_module

    calls: list[tuple] = []

    def _record(feature, **kwargs):
        calls.append((feature, kwargs))

    monkeypatch.setattr(auto_memory_module, "set_usage_scope", _record)

    host = _Host()
    # 短文本会命中质量门提前返回，但 scope 在进入时已设置
    await host._extract_auto_memory(
        scope_key="g:1001",
        user_id=2002,
        sender_name="测试用户",
        user_text="太短",
        assistant_text="同样太短",
        persona_id="nightwatch",
    )

    assert ("auto_memory", {"group_id": "g:1001", "persona_id": "nightwatch"}) in calls


async def test_auto_memory_scope_defaults_persona_to_none(monkeypatch):
    import quickquip.llm.service_parts.auto_memory as auto_memory_module

    calls: list[tuple] = []

    def _record(feature, **kwargs):
        calls.append((feature, kwargs))

    monkeypatch.setattr(auto_memory_module, "set_usage_scope", _record)

    host = _Host()
    await host._extract_auto_memory(
        scope_key="g:1001",
        user_id=2002,
        sender_name="测试用户",
        user_text="太短",
        assistant_text="同样太短",
    )

    assert ("auto_memory", {"group_id": "g:1001", "persona_id": None}) in calls
