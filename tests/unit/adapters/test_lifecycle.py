from __future__ import annotations

import sys
import types

import pytest

from quickquip.adapters.nonebot import lifecycle


class _FakeDriver:
    def __init__(self):
        self.startup = None
        self.shutdown = None

    def on_startup(self, func):
        self.startup = func
        return func

    def on_shutdown(self, func):
        self.shutdown = func
        return func


@pytest.mark.asyncio
async def test_shutdown_closes_stores_even_if_save_all_fails(monkeypatch):
    driver = _FakeDriver()
    calls: list[str] = []

    async def fake_tieba_shutdown():
        calls.append("tieba")

    async def fake_llm_shutdown():
        calls.append("llm")

    def fake_save_all():
        calls.append("save")
        raise RuntimeError("boom")

    def fake_close_persistent_stores():
        calls.append("close")

    fake_scheduler_module = types.ModuleType("nonebot_plugin_apscheduler")
    fake_scheduler_module.scheduler = types.SimpleNamespace(add_job=lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "nonebot_plugin_apscheduler", fake_scheduler_module)
    monkeypatch.setattr(lifecycle, "tieba_service", types.SimpleNamespace(shutdown=fake_tieba_shutdown))
    monkeypatch.setattr(
        lifecycle,
        "get_llm_service",
        lambda: types.SimpleNamespace(shutdown=fake_llm_shutdown, startup=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(lifecycle, "save_all", fake_save_all)
    monkeypatch.setattr(lifecycle, "close_persistent_stores", fake_close_persistent_stores)

    lifecycle.register_lifecycle(driver)

    with pytest.raises(RuntimeError, match="boom"):
        await driver.shutdown()

    assert calls == ["tieba", "llm", "save", "close"]
