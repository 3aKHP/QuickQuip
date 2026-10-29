"""Published configuration, fenced recovery and task resource ownership."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
import pytest

from quickquip.llm.config import PricingRates
from quickquip.llm.config_document import compile_document
from quickquip.llm.config_runtime import ConfigRuntimeWorker, initialize_for_bot
from quickquip.llm.provider import LLMRequest, LLMResponse
from quickquip.llm.service import LLMService
from quickquip.llm.usage import _record_usage


async def test_deployment_gate_rejects_unavailable_store_with_loaded_configuration(
    llm_config_paths, tmp_path, monkeypatch,
):
    from quickquip.llm.config_cli import execute, parser
    from quickquip.llm.config_errors import ConfigError
    from quickquip.llm.store import LLMStore

    def fail_vocab(path):
        raise ValueError("synthetic vocabulary load failure")

    monkeypatch.setattr("quickquip.llm.service.VocabIndex.from_file", fail_vocab)
    llm_service = LLMService(**llm_config_paths)
    service = llm_service.config_service
    worker = ConfigRuntimeWorker(service, llm_service)
    args = parser().parse_args(["--db", str(service.path), "status", "--require-loaded"])
    worker.report()
    assert execute(args)["bot"]["components"]["core"]["state"] == "ready"
    good_store = llm_service.store
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"not a SQLite database")
    llm_service.store = LLMStore(broken)
    assert llm_service.store._unavailable
    worker.report()
    status = service.status()
    assert status["bot"]["loaded_revision"] == status["published_revision"]
    assert not status["bot"]["stale"]
    with pytest.raises(ConfigError) as caught:
        execute(args)
    assert caught.value.code == "bot_not_ready"
    llm_service.store = good_store
    worker.report()
    assert execute(args)["bot"]["components"]["core"]["state"] == "ready"
    await llm_service.shutdown()


async def test_sample_operation_retains_parsed_trace_billing_and_single_dispatch(
    llm_service, monkeypatch, tmp_path
):
    import json
    import httpx
    from quickquip.llm.provider import trace as trace_module
    from quickquip.llm.usage import drain_usage_tasks

    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    trace_store = trace_module.LLMTraceStore(tmp_path / "sample-trace.db")
    monkeypatch.setattr(trace_module, "trace_store", trace_store)
    monkeypatch.setattr("quickquip.llm.provider.trace_store", trace_store)
    rows = []
    monkeypatch.setattr("quickquip.llm.usage_store.usage_store.record", rows.append)
    calls = []
    response_text = ("parsed " * 1500).strip()

    def dispatch(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={
            "model": "gpt-test", "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": response_text,
                "reasoning_content": "synthetic thought",
            }}], "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
        }, request=request)
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(dispatch)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=transport, **kwargs
    ))
    service = llm_service.config_service
    draft = service.read()
    draft["document"]["pricing"] = [{
        "provider_id": "openai-main", "model": "gpt-test",
        "input_per_mtok": 2, "output_per_mtok": 3,
    }]
    service.replace(draft["document"], draft["revision"])
    payload = {"user_prompt": "synthetic sample", "system_prompt": "test",
               "stream": False, "max_output_tokens": 256}
    queued = service.probe("draft", "openai-main", "gpt-test", "sample-once", payload)
    worker = ConfigRuntimeWorker(service, llm_service)
    await worker.tick()
    result = service.tasks.get(queued["id"])
    assert result["status"] == "succeeded"
    parsed = result["result"]
    assert parsed["text"] == response_text
    assert parsed["thinking_blocks"] == [
        {"type": "reasoning", "reasoning_content": "synthetic thought"}
    ]
    assert parsed["duration_ms"] >= 0
    assert parsed["finish_reason"] == "stop"
    assert parsed["input_tokens"] == parsed["output_tokens"] == 1_000_000
    assert len(parsed["trace_calls"]) == 1
    assert json.loads(parsed["trace_calls"][0]["response_text"])["model"] == "gpt-test"
    await drain_usage_tasks()
    assert len(rows) == 1
    assert rows[0]["feature"] == "diagnostics"
    assert rows[0]["config_revision"] == queued["target_revision"]
    assert rows[0]["cost_usd"] == 5
    recovered = service.probe("draft", "openai-main", "gpt-test", "sample-once", payload)
    assert recovered["id"] == queued["id"]
    await worker.tick()
    assert len(calls) == 1
    assert calls[0]["model"] == "gpt-test"
    assert calls[0]["messages"][-1]["content"] == "synthetic sample"
    await llm_service.shutdown()


def enqueue(runtime, change, request_id="apply-test"):
    service = runtime.config_service
    draft = service.read()
    change(draft["document"])
    saved = service.replace(draft["document"], draft["revision"])
    return service.apply(saved["revision"], request_id)


async def test_apply_pins_target_and_old_task_prices(llm_service, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    runtime = llm_service
    runtime.config.pricing_references = {
        ("openai-main", "gpt-test"): PricingRates(input_per_mtok=2, output_per_mtok=3)
    }
    old_revision = runtime.config.revision
    entered = asyncio.Event()
    release = asyncio.Event()
    observed = []
    rows = []
    monkeypatch.setattr("quickquip.llm.usage_store.usage_store.record", rows.append)

    async def long_task():
        async with runtime.configuration_lease():
            entered.set()
            await release.wait()
            observed.append((runtime.config.revision, runtime.config.runtime.max_prompt_chars))
            await _record_usage(
                SimpleNamespace(config=runtime.config.providers["openai-main"]),
                LLMRequest(model="gpt-test", system_prompt="", messages=[],
                           temperature=0, max_output_tokens=1),
                LLMResponse(text="done", model="gpt-test", input_tokens=1_000_000,
                            output_tokens=1_000_000),
                started=0, stream_used=False, state="ok",
            )
    task = asyncio.create_task(long_task())
    await entered.wait()
    operation = enqueue(
        runtime, lambda doc: doc["settings"]["runtime"].update(max_prompt_chars=2000)
    )
    draft = runtime.config_service.read()
    draft["document"]["settings"]["runtime"]["max_prompt_chars"] = 3000
    runtime.config_service.replace(draft["document"], draft["revision"])
    await ConfigRuntimeWorker(runtime.config_service, runtime).tick()
    assert runtime.config.runtime.max_prompt_chars == 2000
    assert runtime.config.revision == operation["target_revision"]
    assert runtime.config_service.tasks.get(operation["id"])["status"] == "succeeded"
    release.set()
    await task
    assert observed == [(old_revision, 1000)]
    assert rows[0]["cost_usd"] == 5
    status = runtime.config_service.status()
    assert status["bot"]["loaded_revision"] == operation["target_revision"]
    assert status["draft_revision"] > status["published_revision"]
    await runtime.shutdown()


async def test_mcp_change_releases_old_generation_after_last_lease(llm_service, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    runtime = llm_service
    old_manager = runtime.mcp_manager
    closed = []
    async def close():
        closed.append(old_manager)
    monkeypatch.setattr(old_manager, "aclose", close)
    entered, release = asyncio.Event(), asyncio.Event()
    retained = []
    async def old_task():
        async with runtime.configuration_lease():
            entered.set()
            await release.wait()
            retained.append(runtime.mcp_manager)
    task = asyncio.create_task(old_task())
    await entered.wait()
    operation = enqueue(runtime, lambda doc: doc["settings"]["mcp"].update(enabled=True))
    await ConfigRuntimeWorker(runtime.config_service, runtime).tick()
    assert runtime.config_service.tasks.get(operation["id"])["status"] == "succeeded"
    assert runtime.mcp_manager is not old_manager
    assert closed == []
    release.set()
    await task
    await asyncio.gather(*runtime._resource_cleanup_tasks)
    assert retained == [old_manager]
    assert closed == [old_manager]
    manager = runtime.mcp_manager
    operation = enqueue(
        runtime, lambda doc: doc["settings"]["runtime"].update(max_prompt_chars=2100),
        request_id="unrelated-change",
    )
    await ConfigRuntimeWorker(runtime.config_service, runtime).tick()
    assert runtime.mcp_manager is manager
    await runtime.shutdown()


async def test_failed_schedules_keep_published_and_loaded_config(llm_service, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    runtime = llm_service
    original = runtime.config.revision
    operation = enqueue(
        runtime, lambda doc: doc["settings"]["runtime"].update(max_prompt_chars=2100)
    )
    def fail_schedule(old, new):
        raise RuntimeError("expanded-secret-sentinel")
    await ConfigRuntimeWorker(runtime.config_service, runtime, schedules=fail_schedule).tick()
    result = runtime.config_service.tasks.get(operation["id"])
    assert result["status"] == "failed"
    assert result["error"]["code"] == "configuration_failed"
    assert "expanded-secret-sentinel" not in str(result)
    assert runtime.config.revision == original
    assert runtime.config_service.read("published")["revision"] == original
    await runtime.shutdown()


async def test_boot_loads_published_and_recovers_publication(llm_service, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    runtime = llm_service
    operation = enqueue(
        runtime, lambda doc: doc["settings"]["runtime"].update(max_prompt_chars=2100)
    )
    claimed = runtime.config_service.tasks.claim("crashed-bot")
    runtime.config_service.publish(claimed["id"], claimed["claim_token"])
    with runtime.config_service.execution.connect(write=True) as conn:
        conn.execute("UPDATE config_operations SET lease_until=0 WHERE id=?", (operation["id"],))
    draft = runtime.config_service.read()
    draft["document"]["settings"]["runtime"]["max_prompt_chars"] = 3100
    runtime.config_service.replace(draft["document"], draft["revision"])
    restarted = LLMService(
        config_path=runtime.config_path, db_path=runtime.store.path,
        identity_path=runtime.identity_path, vocab_path=runtime.vocab_path,
    )
    assert restarted.config.runtime.max_prompt_chars == 2100
    await ConfigRuntimeWorker(runtime.config_service, restarted).tick()
    assert runtime.config_service.tasks.get(operation["id"])["status"] == "succeeded"
    assert runtime.config_service.status()["bot"]["loaded_revision"] == operation["target_revision"]
    await restarted.shutdown()
    await runtime.shutdown()


async def test_async_billing_keeps_snapshot_after_parent_lease_exits(llm_service, monkeypatch):
    from quickquip.llm.usage import _configured_pricing
    gate = asyncio.Event()
    async def billing():
        await gate.wait()
        return _configured_pricing()[("p", "gpt-test")].input_per_mtok
    llm_service.config.pricing_references = {
        ("p", "gpt-test"): PricingRates(input_per_mtok=2, output_per_mtok=0)
    }
    async with llm_service.configuration_lease():
        task = asyncio.create_task(billing())
    llm_service.config = replace(llm_service.config, pricing_references={
        ("p", "gpt-test"): PricingRates(input_per_mtok=20, output_per_mtok=0)
    })
    gate.set()
    assert await task == 2


async def test_model_override_is_used_in_actual_quick_judge_request(llm_service, monkeypatch):
    captured = []
    document = llm_service.config_service.read()["document"]
    document["providers"][0]["models"][0]["parameters"].update(
        timeout_seconds=91, extra_body={"sentinel": True}, reasoning_effort="high"
    )
    llm_service.config = compile_document(
        document, config_dir=llm_service.config_path.parent.parent / "config"
    )
    class Client:
        async def complete(self, request):
            return LLMResponse(text='{"trigger":true}', model=request.model)
    def build(provider):
        captured.append(provider)
        return Client()
    monkeypatch.setattr("quickquip.llm.service.build_provider_client", build)
    await llm_service.quick_judge("question")
    assert captured[0].timeout_seconds == 91
    assert captured[0].extra_body == {"sentinel": True}
    assert captured[0].reasoning_effort == "high"


async def test_skill_directory_change_keeps_old_task_bindings(llm_service, tmp_path, monkeypatch):
    from quickquip.llm.tools import ToolExecutionContext
    from tests.unit.llm.skills.conftest import write_skill
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    old_dir, new_dir = tmp_path / "old-skills", tmp_path / "new-skills"
    write_skill(old_dir, "demo", body="old instructions", files={"references/a.md": "OLD-ASSET"})
    write_skill(new_dir, "demo", body="new instructions", files={"references/a.md": "NEW-ASSET"})
    write_skill(new_dir, "new-only", body="new extra skill")
    runtime = llm_service
    runtime.config = replace(runtime.config, skills=replace(
        runtime.config.skills, catalog_dir=str(old_dir)
    ))
    context = ToolExecutionContext(
        group_id=101, user_id=202, sender_name="test", provider_id="openai-main",
        model="gpt-test", chat_type="group",
    )
    entered, release = asyncio.Event(), asyncio.Event()
    results = []
    async def old_task():
        async with runtime.configuration_lease():
            runtime.prepare_skill_catalog_for_turn(provider=None, model="gpt-test")
            runtime._tool_activate_skill({"name": "demo"}, context)
            entered.set()
            await release.wait()
            results.append(runtime._tool_read_skill_resource(
                {"skill": "demo", "path": "references/a.md"}, context
            ))
            specs = runtime.tool_registry.get_specs(["activate_skill"])
            results.append(specs[0].input_schema["properties"]["name"]["enum"])
    task = asyncio.create_task(old_task())
    await entered.wait()
    manager = runtime.mcp_manager
    enqueue(runtime, lambda doc: doc["settings"]["skills"].update(catalog_dir=str(new_dir)))
    await ConfigRuntimeWorker(runtime.config_service, runtime).tick()
    async with runtime.configuration_lease():
        runtime.prepare_skill_catalog_for_turn(provider=None, model="gpt-test")
        runtime._tool_activate_skill({"name": "demo"}, context)
        new_result = runtime._tool_read_skill_resource(
            {"skill": "demo", "path": "references/a.md"}, context
        )
        assert "NEW-ASSET" in new_result
    release.set()
    await task
    assert "OLD-ASSET" in results[0]
    assert "NEW-ASSET" not in results[0]
    assert results[1] == ["demo"]
    assert runtime.mcp_manager is manager
    await runtime.shutdown()


def test_read_only_bot_waits_for_web_asset_initialization(tmp_path, monkeypatch):
    from quickquip.llm.config_service import ConfigService
    service = ConfigService(tmp_path / "llm_config.db")
    def readonly(_legacy):
        raise PermissionError("readonly assets")
    monkeypatch.setattr(service, "initialize", readonly)
    def initialize_elsewhere(_interval):
        ConfigService(service.path).initialize()
    snapshot = initialize_for_bot(service, sleep=initialize_elsewhere)
    assert snapshot["revision"] == ConfigService(service.path).read("published")["revision"]


def test_read_only_bot_timeout_reports_explicit_migration_requirement(tmp_path, monkeypatch):
    from quickquip.llm.config_errors import ConfigError
    from quickquip.llm.config_service import ConfigService
    service = ConfigService(tmp_path / "llm_config.db")
    def readonly(_legacy):
        raise PermissionError("readonly assets")
    monkeypatch.setattr(service, "initialize", readonly)
    with pytest.raises(ConfigError) as error:
        initialize_for_bot(service, wait_seconds=0)
    assert error.value.code == "migration_required"


async def test_shutdown_drains_task_leases_before_closing_mcp(llm_service, monkeypatch):
    runtime = llm_service
    entered, release = asyncio.Event(), asyncio.Event()
    closed = []
    async def close():
        closed.append(True)
    monkeypatch.setattr(runtime.mcp_manager, "aclose", close)
    async def turn():
        async with runtime.configuration_lease():
            entered.set()
            await release.wait()
            assert closed == []
    task = asyncio.create_task(turn())
    await entered.wait()
    shutdown = asyncio.create_task(runtime.shutdown())
    await asyncio.sleep(0)
    assert not shutdown.done()
    assert closed == []
    release.set()
    await task
    await shutdown
    assert closed == [True]


async def test_manual_runtime_reload_preserves_old_mcp_leases(llm_service, monkeypatch):
    from quickquip.llm.mcp import MCPClientManager
    runtime = llm_service
    old = runtime.mcp_manager
    synced, closed = [], []
    async def sync(manager, _config, **kwargs):
        assert manager is not old
        synced.append(manager)
    async def close():
        closed.append(old)
    monkeypatch.setattr(MCPClientManager, "sync", sync)
    monkeypatch.setattr(old, "aclose", close)
    entered, release = asyncio.Event(), asyncio.Event()
    async def turn():
        async with runtime.configuration_lease():
            entered.set()
            await release.wait()
            assert runtime.mcp_manager is old
            assert closed == []
    task = asyncio.create_task(turn())
    await entered.wait()
    await runtime.reload_runtime()
    assert runtime.mcp_manager is not old
    assert synced == [runtime.mcp_manager]
    assert closed == []
    release.set()
    await task
    await asyncio.gather(*runtime._resource_cleanup_tasks)
    assert closed == [old]
    await runtime.shutdown()


@pytest.mark.parametrize("selection", ["default", "report", "judge", "image", "nonvision"])
async def test_apply_rejects_unavailable_active_selection(llm_service, monkeypatch, selection):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    runtime = llm_service
    original = runtime.config.revision
    def change(document):
        if selection == "default":
            document["providers"][0]["models"][0]["enabled"] = False
            return
        document["settings"]["runtime"]["enabled"] = False
        if selection == "report":
            document["settings"]["daily_summary"]["enabled"] = True
            document["routes"]["daily_summary"] = [
                {"provider_id": "openai-main", "model": "gpt-alt"}
            ]
        elif selection == "judge":
            document["settings"]["quick_judge"].update(provider_id="openai-main", model="gpt-alt")
        else:
            document["settings"]["image_preprocessing"].update(
                enabled=True, provider_id="openai-main", model="gpt-alt"
            )
        if selection == "nonvision":
            document["providers"][0]["models"][1]["vision"] = False
        else:
            document["providers"][0]["models"][1]["enabled"] = False
    operation = enqueue(runtime, change)
    await ConfigRuntimeWorker(runtime.config_service, runtime).tick()
    result = runtime.config_service.tasks.get(operation["id"])
    assert result["status"] == "failed"
    assert result["error"]["code"] == (
        "vision_required" if selection == "nonvision" else "disabled_model"
    )
    assert result["error"]["field_path"]
    assert runtime.config.revision == original
    assert runtime.config_service.read("published")["revision"] == original
    await runtime.shutdown()


@pytest.mark.parametrize("feature", ["weekly_report", "quick_judge", "image_preprocessing"])
async def test_independent_feature_requires_selected_credentials(llm_service, monkeypatch, feature):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    def change(document):
        document["settings"]["runtime"]["enabled"] = False
        if feature == "weekly_report":
            document["settings"][feature]["enabled"] = True
        else:
            document["settings"][feature].update(provider_id="openai-main", model="gpt-test")
            if feature == "image_preprocessing":
                document["settings"][feature]["enabled"] = True
    operation = enqueue(llm_service, change)
    await ConfigRuntimeWorker(llm_service.config_service, llm_service).tick()
    result = llm_service.config_service.tasks.get(operation["id"])
    assert result["status"] == "failed"
    assert result["error"]["code"] == "missing_environment"
    assert result["error"]["details"]["variables"] == ["OPENAI_API_KEY"]
    await llm_service.shutdown()


async def test_selected_auth_header_requires_environment(llm_service, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    monkeypatch.delenv("TEST_SELECTED_HEADER_KEY", raising=False)
    operation = enqueue(llm_service, lambda document: document["providers"][0]["headers"].update(
        Authorization="Bearer ${TEST_SELECTED_HEADER_KEY}"
    ))
    await ConfigRuntimeWorker(llm_service.config_service, llm_service).tick()
    result = llm_service.config_service.tasks.get(operation["id"])
    assert result["status"] == "failed"
    assert result["error"]["code"] == "missing_environment"
    assert result["error"]["details"]["variables"] == ["TEST_SELECTED_HEADER_KEY"]
    await llm_service.shutdown()


async def test_unused_provider_credentials_do_not_block_application(llm_service, monkeypatch):
    from copy import deepcopy
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    monkeypatch.delenv("UNUSED_PROVIDER_KEY", raising=False)
    def change(document):
        unused = deepcopy(document["providers"][0])
        unused.update(id="unused", api_key_env="UNUSED_PROVIDER_KEY")
        document["providers"].append(unused)
    operation = enqueue(llm_service, change)
    await ConfigRuntimeWorker(llm_service.config_service, llm_service).tick()
    assert llm_service.config_service.tasks.get(operation["id"])["status"] == "succeeded"
    await llm_service.shutdown()
