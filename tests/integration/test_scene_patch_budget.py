"""Request-scoped scene snapshots survive assembly and budget reduction."""
from __future__ import annotations

import pytest

from quickquip.common.recent_message_buffer import RecentMessageBuffer
from quickquip.llm.epoch import EpochKey
from quickquip.llm.provider import LLMResponse
from tests.fixtures.provider_stubs import StubBehaviorProviderClient


@pytest.fixture
def scene_service(llm_service, monkeypatch, patch_provider_builder):
    buffer = RecentMessageBuffer(ttl_seconds=3600)
    llm_service.bind_recent_message_buffer(buffer)
    monkeypatch.setattr("quickquip.common.recent_message_buffer.time", lambda: 1000.0)
    buffer.add_message(1001, 3003, "Other", "", "UNSERVED_SCENE", message_id="scene", now_ts=600)
    client = StubBehaviorProviderClient(LLMResponse(text="safe reply", model="gpt-test"))
    patch_provider_builder(lambda provider: client)
    return llm_service, client


async def _reply(service, **kwargs):
    return await service.generate_reply(
        group_id=1001, user_id=2002, sender_name="Test", prompt="Question",
        trigger_auto_memory=False, **kwargs,
    )


async def test_unserved_scene_survives_first_request(scene_service):
    service, client = scene_service
    await _reply(service)
    assert len(client.requests) == 1
    assert "UNSERVED_SCENE" in client.requests[0].messages[-1].content
    await _reply(service)
    assert "UNSERVED_SCENE" not in client.requests[-1].messages[-1].content


@pytest.mark.parametrize("budget, expected_calls", [(8000, 1), (100, 0)])
async def test_budget_rebuild_preserves_scene(scene_service, monkeypatch, budget, expected_calls):
    service, client = scene_service
    runtime = service.config.runtime
    for name, value in {
        "epoch_context_tokens": 50000, "epoch_cold_target_tokens": 100,
        "epoch_cold_trigger_tokens": 200, "epoch_hot_target_tokens": 500,
        "epoch_cap_tokens": 100000, "request_input_token_budget": budget,
    }.items():
        monkeypatch.setattr(runtime, name, value)
    for index in range(12):
        service.store.append_conversation_message(1001, "3003", "user", f"old{index} " * 500)
        service.store.append_conversation_message(1001, None, "assistant", "answer " * 500)
    key = EpochKey("1001", "openai-main", "gpt-test")
    service._epochs.maybe_advance(key, store=service.store, params=service.config.resolve_epoch_params())
    before = service._epochs.current_anchor(key)
    result = await _reply(service)
    assert service._epochs.current_anchor(key) > before
    assert len(client.requests) == expected_calls
    if expected_calls:
        assert result["reply"] == "safe reply"
        assert "UNSERVED_SCENE" in client.requests[0].messages[-1].content
    else:
        assert result["llm_used"] is False


async def test_history_added_during_preprocessing_deduplicates_snapshot(scene_service, monkeypatch):
    service, client = scene_service
    original = service._preprocess_images_for_model

    async def preprocess(**kwargs):
        service.store.append_conversation_message(
            1001, "3003", "user", "UNSERVED_SCENE", message_id="scene",
        )
        return await original(**kwargs)

    monkeypatch.setattr(service, "_preprocess_images_for_model", preprocess)
    await _reply(service)
    text = "\n".join(message.content for message in client.requests[0].messages)
    assert text.count("UNSERVED_SCENE") == 1
    assert "【现场】" not in client.requests[0].messages[-1].content
