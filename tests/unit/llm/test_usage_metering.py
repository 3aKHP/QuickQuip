import asyncio

import httpx
import pytest
from plugins.llm_config import ProviderConfig
from plugins.llm_provider import LLMRequest
from plugins.llm_tools import LLMConversationMessage

from quickquip.llm.usage import drain_usage_tasks
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

    monkeypatch.setattr("quickquip.llm.usage._record_usage", spy)
    client = FakeClaudeClient(
        _config(),
        {"content": [], "usage": {"input_tokens": 10, "output_tokens": 5}},
    )
    await client.complete(_req())
    await drain_usage_tasks()
    assert calls == [("ok", True)]


async def test_complete_does_not_await_usage_record(monkeypatch):
    """complete() 的返回不等待计量任务：计量阻塞时聊天回复仍及时（Issue #111 #1）。

    spy 阻塞在 gate 上永不自行结束；若 complete() 仍 await 计量，wait_for 会超时。
    """
    gate = asyncio.Event()
    entered = asyncio.Event()
    calls = []

    async def spy(client, request, response, started, stream_used, state, error_msg=""):
        calls.append(state)
        entered.set()
        await gate.wait()

    monkeypatch.setattr("quickquip.llm.usage._record_usage", spy)
    client = FakeClaudeClient(
        _config(),
        {"content": [], "usage": {"input_tokens": 10, "output_tokens": 5}},
    )
    try:
        response = await asyncio.wait_for(client.complete(_req()), timeout=1.0)
        assert response is not None  # gate 未放行，回复已经返回
        await asyncio.wait_for(entered.wait(), timeout=1.0)  # 计量任务确已启动并阻塞
        assert calls == ["ok"]
    finally:
        gate.set()  # 失败路径也必须放行，避免阻塞任务泄漏给后续测试的 drain
    await drain_usage_tasks()
    assert calls == ["ok"]


async def test_complete_error_records_state(monkeypatch):
    calls = []

    async def spy(client, request, response, started, stream_used, state, error_msg=""):
        calls.append((state, response))

    monkeypatch.setattr("quickquip.llm.usage._record_usage", spy)
    client = FakeClaudeClient(_config(), {"content": []})

    async def _raise(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(client, "_post_json", _raise)
    with pytest.raises(RuntimeError):
        await client.complete(_req())
    await drain_usage_tasks()
    assert calls == [("error", None)]


async def test_complete_cancelled_propagates(monkeypatch):
    """cancelled 记录经独立任务调度（父协程取消后仍存活）；此处断言
    CancelledError 正确传播且计量任务仍被调度执行。"""
    calls = []

    async def spy(client, request, response, started, stream_used, state, error_msg=""):
        calls.append((state, response))

    monkeypatch.setattr("quickquip.llm.usage._record_usage", spy)
    client = FakeClaudeClient(_config(), {"content": []})

    async def _hang(*a, **kw):
        await asyncio.sleep(100)

    monkeypatch.setattr(client, "_post_json", _hang)
    task = asyncio.create_task(client.complete(_req()))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await drain_usage_tasks()
    assert calls == [("cancelled", None)]


async def test_complete_error_message_masks_url(monkeypatch, tmp_path):
    """Issue #111 #4：error_message 落库前遮蔽 URL（httpx 错误串含完整请求 URL
    及潜在 query 凭据）；写入 conftest 指向的临时 usage 库。"""
    client = FakeClaudeClient(_config(), {"content": []})

    async def _raise(*a, **kw):
        raise httpx.ConnectError(
            "connection refused for https://api.example.com/v1/messages?key=SECRET"
        )

    monkeypatch.setattr(client, "_post_json", _raise)
    with pytest.raises(httpx.ConnectError):
        await client.complete(_req())
    await drain_usage_tasks()

    from quickquip.llm import usage_store as usage_store_module
    with usage_store_module.usage_store.connect() as conn:
        row = conn.execute("SELECT error_message FROM llm_usage_events").fetchone()
    assert row["error_message"].startswith("ConnectError:")
    assert "[url]" in row["error_message"]
    assert "SECRET" not in row["error_message"]
    assert "api.example.com" not in row["error_message"]


async def test_record_usage_carries_envelope_tokens_within_meter(monkeypatch, tmp_path):
    """envelope_meter 内落的行带 envelope_tokens，meter 外落行则为 NULL；
    同 meter 内多行（Agent Loop 多次 complete）带同值。"""
    from quickquip.llm.usage import _record_usage, envelope_meter
    from quickquip.llm.usage_store import LLMUsageStore
    from plugins.llm_config import ProviderConfig
    from plugins.llm_provider import LLMResponse

    fake_store = LLMUsageStore(tmp_path / "u.db")
    monkeypatch.setattr("quickquip.llm.usage_store.usage_store", fake_store)

    class FakeClient:
        config = ProviderConfig(
            id="p", protocol="claude", base_url="https://x/v1",
            api_key_env="K", default_model="m", models=["m"],
        )

    class FakeReq:
        model = "m"

    response = LLMResponse(text="ok", model="m", input_tokens=10, output_tokens=5)
    with envelope_meter(456):
        await _record_usage(FakeClient(), FakeReq(), response, 0.0, True, "ok")
        await _record_usage(FakeClient(), FakeReq(), response, 0.0, True, "ok")
    await _record_usage(FakeClient(), FakeReq(), response, 0.0, True, "ok")
    with fake_store.connect() as conn:
        rows = conn.execute(
            "SELECT envelope_tokens FROM llm_usage_events ORDER BY id"
        ).fetchall()
    assert [r["envelope_tokens"] for r in rows] == [456, 456, None]


async def test_record_usage_carries_epoch_history_tokens_within_meter(monkeypatch, tmp_path):
    """epoch_meter 内落的行带 epoch_history_tokens，meter 外落行则为 NULL；
    同 meter 内多行（Agent Loop 多次 complete）带同值。"""
    from quickquip.llm.usage import _record_usage, epoch_meter
    from quickquip.llm.usage_store import LLMUsageStore
    from plugins.llm_config import ProviderConfig
    from plugins.llm_provider import LLMResponse

    fake_store = LLMUsageStore(tmp_path / "u.db")
    monkeypatch.setattr("quickquip.llm.usage_store.usage_store", fake_store)

    class FakeClient:
        config = ProviderConfig(
            id="p", protocol="claude", base_url="https://x/v1",
            api_key_env="K", default_model="m", models=["m"],
        )

    class FakeReq:
        model = "m"

    response = LLMResponse(text="ok", model="m", input_tokens=10, output_tokens=5)
    with epoch_meter(4200):
        await _record_usage(FakeClient(), FakeReq(), response, 0.0, True, "ok")
        await _record_usage(FakeClient(), FakeReq(), response, 0.0, True, "ok")
    await _record_usage(FakeClient(), FakeReq(), response, 0.0, True, "ok")
    with fake_store.connect() as conn:
        rows = conn.execute(
            "SELECT epoch_history_tokens FROM llm_usage_events ORDER BY id"
        ).fetchall()
    assert [r["epoch_history_tokens"] for r in rows] == [4200, 4200, None]


async def test_record_usage_writes_db_row(monkeypatch, tmp_path):
    """e2e: 真实 _record_usage 把 row 写入 store（验证 row dict 列名匹配 schema）。"""
    from quickquip.llm.usage import _record_usage
    from quickquip.llm.usage_store import LLMUsageStore
    from plugins.llm_config import ProviderConfig
    from plugins.llm_provider import LLMResponse

    fake_store = LLMUsageStore(tmp_path / "u.db")
    monkeypatch.setattr("quickquip.llm.usage_store.usage_store", fake_store)

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


async def test_record_usage_uses_provider_level_pricing(monkeypatch, tmp_path):
    """e2e: _record_usage 传 client.config.id，provider 级价（覆盖 model 默认）落 cost_usd。"""
    from quickquip.llm.config import PricingRates
    from quickquip.llm.usage import _record_usage
    from quickquip.llm.usage_store import LLMUsageStore
    from plugins.llm_config import ProviderConfig
    from plugins.llm_provider import LLMResponse

    fake_store = LLMUsageStore(tmp_path / "u.db")
    monkeypatch.setattr("quickquip.llm.usage_store.usage_store", fake_store)
    configured = {
        "gpt-test": PricingRates(input_per_mtok=1.0, output_per_mtok=5.0),
        "p1/gpt-test": PricingRates(input_per_mtok=2.0, output_per_mtok=10.0),
    }
    monkeypatch.setattr("quickquip.llm.usage._configured_pricing", lambda: configured)

    class FakeClient:
        config = ProviderConfig(
            id="p1", protocol="openai", base_url="https://x/v1",
            api_key_env="K", default_model="gpt-test", models=["gpt-test"],
        )

    class FakeReq:
        model = "gpt-test"

    response = LLMResponse(text="ok", model="gpt-test", input_tokens=100, output_tokens=50)
    await _record_usage(FakeClient(), FakeReq(), response, 0.0, True, "ok")
    with fake_store.connect() as conn:
        row = conn.execute("SELECT cost_usd, priced FROM llm_usage_events").fetchone()
    # provider p1 覆盖价（非 model 默认）：actual_input 100*2 + completion 50*10（per MTok）
    expected = 100 * 2 / 1e6 + 50 * 10 / 1e6
    assert abs(row["cost_usd"] - expected) < 1e-9
    assert row["priced"] == 1
