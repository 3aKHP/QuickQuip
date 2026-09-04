import asyncio

from quickquip.llm.usage import (
    _ENVELOPE_TOKENS,
    _EPOCH_HISTORY_TOKENS,
    _MEDIA_IMAGE_COUNT,
    _PATCH_TOKENS,
    _USAGE_SCOPE,
    envelope_meter,
    epoch_meter,
    media_meter,
    patch_meter,
    set_usage_scope,
    usage_scope,
)


def test_patch_meter_sets_and_resets():
    assert _PATCH_TOKENS.get() is None
    with patch_meter(360):
        assert _PATCH_TOKENS.get() == 360
    assert _PATCH_TOKENS.get() is None


def test_patch_meter_nested_inner_resets_to_outer():
    with patch_meter(100):
        with patch_meter(300):
            assert _PATCH_TOKENS.get() == 300
        assert _PATCH_TOKENS.get() == 100
    assert _PATCH_TOKENS.get() is None


def test_media_meter_sets_and_resets():
    assert _MEDIA_IMAGE_COUNT.get() is None
    with media_meter(2):
        assert _MEDIA_IMAGE_COUNT.get() == 2
    assert _MEDIA_IMAGE_COUNT.get() is None


def test_media_meter_nested_inner_resets_to_outer():
    with media_meter(1):
        with media_meter(3):
            assert _MEDIA_IMAGE_COUNT.get() == 3
        assert _MEDIA_IMAGE_COUNT.get() == 1
    assert _MEDIA_IMAGE_COUNT.get() is None


def test_epoch_meter_sets_and_resets():
    assert _EPOCH_HISTORY_TOKENS.get() is None
    with epoch_meter(4200):
        assert _EPOCH_HISTORY_TOKENS.get() == 4200
    assert _EPOCH_HISTORY_TOKENS.get() is None


def test_epoch_meter_nested_inner_resets_to_outer():
    with epoch_meter(4000):
        with epoch_meter(8000):
            assert _EPOCH_HISTORY_TOKENS.get() == 8000
        assert _EPOCH_HISTORY_TOKENS.get() == 4000
    assert _EPOCH_HISTORY_TOKENS.get() is None


def test_envelope_meter_sets_and_resets():
    assert _ENVELOPE_TOKENS.get() is None
    with envelope_meter(123):
        assert _ENVELOPE_TOKENS.get() == 123
    assert _ENVELOPE_TOKENS.get() is None


def test_envelope_meter_nested_inner_resets_to_outer():
    with envelope_meter(100):
        with envelope_meter(200):
            assert _ENVELOPE_TOKENS.get() == 200
        assert _ENVELOPE_TOKENS.get() == 100
    assert _ENVELOPE_TOKENS.get() is None


def test_usage_scope_contextmanager_sets_and_resets():
    assert _USAGE_SCOPE.get() is None
    with usage_scope("chat", group_id="g1", persona_id="p1"):
        scope = _USAGE_SCOPE.get()
        assert scope is not None
        assert scope.feature == "chat"
        assert scope.group_id == "g1"
        assert scope.persona_id == "p1"
    assert _USAGE_SCOPE.get() is None


def test_usage_scope_nested_inner_resets_to_outer():
    with usage_scope("chat", group_id="g"):
        assert _USAGE_SCOPE.get().feature == "chat"
        with usage_scope("vision"):
            assert _USAGE_SCOPE.get().feature == "vision"
            assert _USAGE_SCOPE.get().group_id is None
        assert _USAGE_SCOPE.get().feature == "chat"
        assert _USAGE_SCOPE.get().group_id == "g"
    assert _USAGE_SCOPE.get() is None


def test_set_usage_scope_does_not_reset():
    """set_usage_scope 不 reset（用于 create_task 隔离子任务）。"""
    try:
        assert _USAGE_SCOPE.get() is None
        set_usage_scope("health")
        assert _USAGE_SCOPE.get().feature == "health"
    finally:
        _USAGE_SCOPE.set(None)


async def test_usage_scope_propagates_along_await_chain():
    """ContextVar 在同一协程的 await 链上传播（接线有效性的前提）。"""
    seen: list[str] = []

    async def inner():
        scope = _USAGE_SCOPE.get()
        seen.append(scope.feature if scope else None)

    with usage_scope("chat", group_id="g"):
        await inner()
        await asyncio.sleep(0)  # 让出一次事件循环
        await inner()
    assert seen == ["chat", "chat"]


async def test_record_usage_reads_usage_scope(monkeypatch, tmp_path):
    """接线有效性核心：usage_scope 设的 feature/group_id 经 _record_usage 正确落库。"""
    from plugins.llm_config import ProviderConfig
    from plugins.llm_provider import LLMResponse

    from quickquip.llm.usage import _record_usage
    from quickquip.llm.usage_store import LLMUsageStore

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
    with usage_scope("chat", group_id="g42", persona_id="p7"):
        await _record_usage(FakeClient(), FakeReq(), response, 0.0, True, "ok")
    with fake_store.connect() as conn:
        row = conn.execute(
            "SELECT feature, group_id, persona_id FROM llm_usage_events"
        ).fetchone()
    assert row["feature"] == "chat"
    assert row["group_id"] == "g42"
    assert row["persona_id"] == "p7"
