from __future__ import annotations

import asyncio
from dataclasses import replace

from quickquip.llm.epoch import EpochKey, EpochManager
from quickquip.llm.image_preprocessor import ImageDescription
from quickquip.llm.provider import LLMResponse
from quickquip.llm.store import LLMStore
from tests.fixtures.provider_stubs import StubProviderClient, StubToolCallingProviderClient


async def _reply(service, **overrides):
    args = dict(group_id=1001, user_id=2002, sender_name="user", prompt="hello")
    args.update(overrides)
    return await service.generate_reply(**args)


async def test_chat_identity_survives_rounds_model_persona_idle_crop_and_restart(
    llm_service, patch_provider_builder,
):
    now = [0.0]
    llm_service._epochs = EpochManager(clock=lambda: now[0])
    llm_service.config.runtime = replace(
        llm_service.config.runtime,
        epoch_cold_idle_seconds=1, epoch_cold_trigger_tokens=100, epoch_cold_target_tokens=50,
    )
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)
    await _reply(llm_service)
    original = stub.last_request.session
    for _ in range(8):
        llm_service.store.append_conversation_message("1001", "u", "user", "context " * 40)
        llm_service.store.append_conversation_message("1001", None, "assistant", "answer " * 40)
    key = EpochKey("1001", "openai-main", "gpt-test")
    old_anchor = llm_service._epochs.current_anchor(key)
    now[0] = 10.0
    await _reply(llm_service, user_id=2003)
    assert llm_service._epochs.current_anchor(key) > old_anchor
    assert stub.last_request.session == original
    llm_service.set_group_model(1001, "openai-main", "gpt-alt")
    llm_service.set_group_persona(1001, "default")
    await _reply(llm_service)
    assert stub.last_request.session == original
    llm_service.set_group_enabled(1001, False)
    await _reply(llm_service)
    assert llm_service.store.get_chat_session("1001") == original
    llm_service.set_group_enabled(1001, True)
    llm_service.store = LLMStore(llm_service.store.path)
    await _reply(llm_service)
    assert stub.last_request.session == original
    llm_service.clear_context(1001)
    await _reply(llm_service)
    assert stub.last_request.session != original


async def test_tool_discovery_and_continuation_keep_the_frozen_identity(
    llm_service, patch_provider_builder,
):
    stub = StubToolCallingProviderClient()
    patch_provider_builder(lambda provider: stub)
    await _reply(llm_service)
    assert len(stub.requests) >= 2
    identity = llm_service.store.get_chat_session("1001")
    assert all(request.session == identity for request in stub.requests)


async def test_clear_during_legacy_model_call_drops_late_reply(
    llm_service, patch_provider_builder,
):
    started, release = asyncio.Event(), asyncio.Event()
    requests = []

    class Client:
        async def complete(self, request):
            requests.append(request)
            started.set()
            await release.wait()
            return LLMResponse(text="late answer", model=request.model)

    patch_provider_builder(lambda provider: Client())
    task = asyncio.create_task(_reply(llm_service, store_user_message=False))
    await asyncio.wait_for(started.wait(), 5)
    original = requests[0].session
    llm_service.clear_context(1001)
    release.set()
    result = await task
    assert result["reply"] == ""
    assert result["cancelled_reason"] == "session_invalidated"
    assert llm_service.store.count_conversation_messages("1001") == 0
    assert llm_service.store.get_chat_session("1001") is None
    replacement, _ = llm_service.store.get_or_create_chat_session("1001")
    assert replacement != original


async def test_clear_during_preprocessing_prevents_main_dispatch(
    llm_service, patch_provider_builder,
):
    started, release = asyncio.Event(), asyncio.Event()
    observed = []

    class Preprocessor:
        async def describe_images(self, urls, *, session=None):
            observed.append(session)
            started.set()
            await release.wait()
            return [ImageDescription(url, "description", True) for url in urls]

    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)
    llm_service.config.providers["openai-main"].non_vision_models.append("gpt-test")
    llm_service.image_preprocessor = Preprocessor()
    task = asyncio.create_task(_reply(llm_service, image_urls=["https://example.test/a.png"]))
    await asyncio.wait_for(started.wait(), 5)
    assert observed == [llm_service.store.get_chat_session("1001")]
    llm_service.clear_context(1001)
    release.set()
    result = await task
    assert result["cancelled_reason"] == "session_invalidated"
    assert stub.last_request is None


async def test_store_failure_stops_dispatch_and_empty_input_does_not_allocate(
    llm_service, patch_provider_builder,
):
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)
    await _reply(llm_service, prompt="")
    assert llm_service.store.get_chat_session("1001") is None
    llm_service.store._unavailable = True
    result = await _reply(llm_service)
    assert result["llm_used"] is False
    assert "存储" in result["reply"]
    assert stub.last_request is None


async def test_archive_inflight_loop_and_resume_do_not_block_next_round(
    llm_service, patch_provider_builder,
):
    started, release = asyncio.Event(), asyncio.Event()

    class Client:
        async def complete(self, request):
            started.set()
            await release.wait()
            return LLMResponse(text="late", model=request.model)

    llm_service.start_private_session(2002)
    original = llm_service.store.get_chat_session("private:2002")
    patch_provider_builder(lambda provider: Client())
    args = dict(user_id=2002, sender_name="user", prompt="hello")
    task = asyncio.create_task(llm_service.generate_private_reply(**args))
    await asyncio.wait_for(started.wait(), 5)
    archived = llm_service.end_private_session(2002)
    assert archived["archive_number"] == 1
    with llm_service.store._connect() as conn:
        pending = conn.execute(
            "SELECT COUNT(*) FROM agent_loops WHERE closed_at IS NULL",
        ).fetchone()
        assert pending[0] == 0
    llm_service.resume_private_session(2002, 1)
    assert llm_service.store.get_chat_session("private:2002") == original
    release.set()
    assert (await task)["cancelled_reason"] == "session_invalidated"
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)
    result = await llm_service.generate_private_reply(**args)
    assert "stub::" in result["reply"]
    assert stub.last_request.session == original
    assert llm_service._scope_gate.bypassed_count == 0
