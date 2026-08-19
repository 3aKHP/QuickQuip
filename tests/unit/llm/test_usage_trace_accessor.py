"""Public trace accessor tests for usage attribution (#111)."""

from __future__ import annotations

import inspect

from quickquip.llm.provider.trace import current_agent_loop_id, trace_agent_loop


def test_current_agent_loop_id_outside_boundary_is_none():
    assert current_agent_loop_id() is None


async def test_current_agent_loop_id_inside_boundary():
    @trace_agent_loop
    async def inner() -> str | None:
        return current_agent_loop_id()

    loop_id = await inner()
    assert loop_id is not None and len(loop_id) > 0
    # 边界退出后复位
    assert current_agent_loop_id() is None


async def test_nested_boundaries_share_one_loop_id():
    outer_ids: list[str | None] = []

    @trace_agent_loop
    async def inner() -> None:
        outer_ids.append(current_agent_loop_id())

    @trace_agent_loop
    async def outer() -> None:
        outer_ids.append(current_agent_loop_id())
        await inner()
        outer_ids.append(current_agent_loop_id())

    await outer()
    assert outer_ids[0] is not None
    assert outer_ids[0] == outer_ids[1] == outer_ids[2]


async def test_record_usage_attributes_agent_loop(monkeypatch, tmp_path):
    """agent loop 边界内的 provider 调用经 _record_usage 记录 loop_id。"""
    from plugins.llm_config import ProviderConfig
    from plugins.llm_provider import LLMResponse

    from quickquip.llm.usage import _record_usage
    from quickquip.llm.usage_store import LLMUsageStore

    store = LLMUsageStore(tmp_path / "usage.db")

    import quickquip.llm.usage_store as usage_store_module

    monkeypatch.setattr(usage_store_module, "usage_store", store)

    # _record_usage 延迟 import usage_store 单例；直接 patch 模块属性即可生效
    client = type(
        "FakeClient",
        (),
        {"config": ProviderConfig(
            id="p", protocol="openai", base_url="https://example.test",
            api_key_env="K", default_model="m", models=["m"],
        )},
    )()
    request = type("FakeRequest", (), {"model": "m"})()
    response = LLMResponse(text="ok", model="m", finish_reason="stop")

    @trace_agent_loop
    async def call_inside_loop() -> None:
        await _record_usage(client, request, response, 0.0, False, "ok")

    await call_inside_loop()
    await _record_usage(client, request, response, 0.0, False, "ok")

    rows = store.events(cutoff="2000-01-01T00:00:00+00:00")["items"]
    assert len(rows) == 2
    assert rows[1]["agent_loop_id"]  # 边界内：有 loop_id
    assert rows[0]["agent_loop_id"] is None  # 边界外：无 loop_id


def test_usage_module_has_no_private_trace_symbols():
    """usage.py 只经公开 accessor 读取 agent loop，不导入私有 Trace symbol。"""
    import quickquip.llm.usage as usage_module

    source = inspect.getsource(usage_module)
    assert "_AGENT_LOOP_TRACE" not in source
    assert "AgentLoopTrace" not in source
    assert "current_agent_loop_id" in source
