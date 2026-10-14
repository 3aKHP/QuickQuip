"""A superseded boot cannot regress publication, loaded state, or admit new work."""
from __future__ import annotations

import asyncio

import pytest

from quickquip.llm.config_document import compile_document
from quickquip.llm.config_errors import ConfigError
from quickquip.llm.config_runtime import ConfigRuntimeWorker
from quickquip.llm.service import LLMService


@pytest.mark.parametrize("paused_boundary", ["publication", "activation"])
async def test_resumed_old_boot_is_fenced_after_new_bot_applies_later_revision(
    llm_service, monkeypatch, paused_boundary
):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    old = llm_service
    service = old.config_service
    first_worker = ConfigRuntimeWorker(service, old)
    entered, release = asyncio.Event(), asyncio.Event()
    old_turn_versions = []
    async def already_started_turn():
        async with old.configuration_lease():
            entered.set()
            await release.wait()
            old_turn_versions.append(old.config.revision)
    turn = asyncio.create_task(already_started_turn())
    await entered.wait()
    draft = service.read()
    draft["document"]["settings"]["runtime"]["max_prompt_chars"] = 2200
    saved = service.replace(draft["document"], draft["revision"])
    first_operation = service.apply(saved["revision"], "first-apply")
    original_publish = service.publish
    original_activate = old.activate_configuration
    replacement = {}

    def takeover():
        # This synchronous pause hook models another process operating while this
        # worker is stopped immediately after its durable or in-memory commit.
        restarted = LLMService(
            config_path=old.config_path, db_path=old.store.path,
            identity_path=old.identity_path, vocab_path=old.vocab_path,
        )
        worker = ConfigRuntimeWorker(service, restarted)
        replacement.update(runtime=restarted, worker=worker)
        with service.store.connect(write=True) as conn:
            conn.execute("UPDATE config_operations SET lease_until=0 WHERE id=?",
                         (first_operation["id"],))
        recovered = service.tasks.claim(worker.boot_id, boot_id=worker.boot_id)
        original_publish(recovered["id"], recovered["claim_token"], boot_id=worker.boot_id)
        service.tasks.finish(recovered["id"], recovered["claim_token"])
        next_draft = service.read()
        next_draft["document"]["settings"]["runtime"]["max_prompt_chars"] = 3300
        next_saved = service.replace(next_draft["document"], next_draft["revision"])
        service.apply(next_saved["revision"], "second-apply")
        claimed = service.tasks.claim(worker.boot_id, boot_id=worker.boot_id)
        original_publish(claimed["id"], claimed["claim_token"], boot_id=worker.boot_id)
        document = service.read(claimed["target_revision"])
        config = compile_document(
            document["document"], revision=document["revision"],
            config_dir=old.config_path.parent.parent / "config",
        )
        restarted.activate_configuration(restarted.prepare_configuration(config))
        worker.report()
        service.tasks.finish(claimed["id"], claimed["claim_token"])

    def publish(*args, **kwargs):
        result = original_publish(*args, **kwargs)
        if paused_boundary == "publication":
            takeover()
        return result

    def activate(snapshot):
        original_activate(snapshot)
        if paused_boundary == "activation":
            takeover()

    monkeypatch.setattr(service, "publish", publish)
    monkeypatch.setattr(old, "activate_configuration", activate)
    await first_worker.tick()
    latest = service.status()
    assert latest["published_revision"] == 3
    assert latest["bot"]["loaded_revision"] == 3
    assert latest["bot"]["boot_id"] == replacement["worker"].boot_id
    latest_epoch = int(replacement["worker"].boot_id.split(":")[0])
    assert latest_epoch > int(first_worker.boot_id.split(":")[0])
    assert old._configuration_fenced
    with pytest.raises(ConfigError, match="newer bot boot"):
        async with old.configuration_lease():
            pytest.fail("Superseded boot admitted a new task")
    with pytest.raises(ConfigError):
        _ = old.config
    with pytest.raises(ConfigError):
        first_worker.report()
    assert service.status()["bot"]["loaded_revision"] == 3
    release.set()
    await turn
    assert old_turn_versions == [1]
    await old.shutdown()
    await replacement["runtime"].shutdown()
