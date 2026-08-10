import asyncio

import pytest
from plugins.llm_config import ProviderConfig
from plugins.llm_provider import LLMRequest
from plugins.llm_tools import LLMConversationMessage

from tests.fixtures.provider_fakes import FakeClaudeClient


def _config() -> ProviderConfig:
    return ProviderConfig(
        id="fake", protocol="claude", base_url="https://x/v1",
        api_key_env="K", default_model="m", models=["m"],
    )


def _req() -> LLMRequest:
    return LLMRequest(
        model="m", system_prompt="s",
        messages=[LLMConversationMessage(role="user", content="hi", image_urls=[])],
        temperature=0.2, max_output_tokens=64,
    )


async def test_complete_ok_records_usage(monkeypatch):
    calls = []

    async def spy(client, request, response, started, stream_used, state, error_msg=""):
        calls.append((state, response is not None))

    monkeypatch.setattr("quickquip.llm.provider.base._record_usage", spy)
    client = FakeClaudeClient(
        _config(),
        {"content": [], "usage": {"input_tokens": 10, "output_tokens": 5}},
    )
    await client.complete(_req())
    assert calls == [("ok", True)]


async def test_complete_error_records_state(monkeypatch):
    calls = []

    async def spy(client, request, response, started, stream_used, state, error_msg=""):
        calls.append((state, response))

    monkeypatch.setattr("quickquip.llm.provider.base._record_usage", spy)
    client = FakeClaudeClient(_config(), {"content": []})

    async def _raise(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(client, "_post_json", _raise)
    with pytest.raises(RuntimeError):
        await client.complete(_req())
    assert calls == [("error", None)]


async def test_complete_cancelled_propagates(monkeypatch):
    """cancelled 记录是 best-effort（shield 在 task 退出时可能丢失，参照 trace）；
    这里只断言 CancelledError 正确传播。"""

    async def spy(*a, **kw):
        pass

    monkeypatch.setattr("quickquip.llm.provider.base._record_usage", spy)
    client = FakeClaudeClient(_config(), {"content": []})

    async def _hang(*a, **kw):
        await asyncio.sleep(100)

    monkeypatch.setattr(client, "_post_json", _hang)
    task = asyncio.create_task(client.complete(_req()))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_record_usage_writes_db_row(monkeypatch, tmp_path):
    """e2e: 真实 _record_usage 把 row 写入 store（验证 row dict 列名匹配 schema）。"""
    from quickquip.llm.usage import _record_usage
    from quickquip.llm.usage_store import LLMUsageStore
    from plugins.llm_config import ProviderConfig
    from plugins.llm_provider import LLMResponse

    fake_store = LLMUsageStore(tmp_path / "u.db")
    monkeypatch.setattr("quickquip.app.message_pipeline.usage_store", fake_store)

    class FakeClient:
        config = ProviderConfig(
            id="p", protocol="claude", base_url="https://x/v1",
            api_key_env="K", default_model="m", models=["m"],
        )

    class FakeReq:
        model = "m"

    response = LLMResponse(
        text="ok", model="m", input_tokens=100, output_tokens=50,
        cache_creation_tokens=80, cache_read_tokens=200,
    )
    await _record_usage(FakeClient(), FakeReq(), response, 0.0, True, "ok")
    with fake_store.connect() as conn:
        row = conn.execute(
            "SELECT state, input_tokens, cost_usd, priced FROM llm_usage_events"
        ).fetchone()
    assert row["state"] == "ok"
    assert row["input_tokens"] == 100
    assert row["cost_usd"] == 0.0  # 无 pricing 配置 → 未定价
    assert row["priced"] == 0
