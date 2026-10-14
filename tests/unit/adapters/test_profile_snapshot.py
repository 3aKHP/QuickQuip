"""A profile command pins persona/style/model through asynchronous archive reads."""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

from quickquip.adapters.nonebot.command_parts import history
from quickquip.llm.config_runtime import ConfigRuntimeWorker


async def test_profile_keeps_model_style_and_revision_during_config_application(
    llm_service, monkeypatch
):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    service = llm_service.config_service
    worker = ConfigRuntimeWorker(service, llm_service)
    draft = service.read()
    draft["document"]["providers"][0]["parameters"]["style_overrides"] = "CHANNEL-STYLE"
    draft["document"]["providers"][0]["models"][0]["parameters"]["style_overrides"] = "MODEL-OLD"
    saved = service.replace(draft["document"], draft["revision"])
    service.apply(saved["revision"], "profile-initial")
    await worker.tick()
    initial_revision = llm_service.config.revision
    matchers = {}
    class Matcher:
        def handle(self):
            def install(function):
                self.handler = function
                return function
            return install
        async def send(self, message):
            pass
        async def finish(self, message):
            raise AssertionError(f"Profile failed: {message}")
    def command(name, **kwargs):
        matchers[name] = Matcher()
        return matchers[name]
    history.register_history_commands(command, str, SimpleNamespace(text=str))
    monkeypatch.setattr(history, "get_llm_service", lambda: llm_service)
    monkeypatch.setattr(history, "_ensure_llm_bindings", lambda: None)
    monkeypatch.setattr(history, "stats_tracker", SimpleNamespace(
        get_stats=lambda group: SimpleNamespace(user_messages={"2002": 2})
    ))
    monkeypatch.setattr(history, "identities", SimpleNamespace(
        snapshot=lambda group: SimpleNamespace(name=lambda user: "Target")
    ))
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    def archive_read(*args):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(timeout=10)
        return [{"user_id": "2002", "text": "sample"}]
    monkeypatch.setattr(history.chat_archive, "read_window", archive_read)
    captured = {}
    async def generate(**kwargs):
        captured.update(kwargs)
        return "Generated profile", "openai-main/gpt-test"
    monkeypatch.setattr(history, "generate_profile", generate)
    monkeypatch.setattr(history, "send_long_group_message", AsyncMock())
    event = SimpleNamespace(
        group_id=1001, message_type="group",
        get_message=lambda: "/profile [CQ:at,qq=2002]",
    )
    task = asyncio.create_task(matchers["profile"].handler(SimpleNamespace(), event))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        next_draft = service.read()
        parameters = next_draft["document"]["providers"][0]["models"][0]["parameters"]
        parameters["style_overrides"] = "MODEL-NEW"
        next_saved = service.replace(next_draft["document"], next_draft["revision"])
        service.apply(next_saved["revision"], "profile-new")
        await worker.tick()
        release.set()
        await task
        assert captured["llm_config"].revision == initial_revision
        assert "MODEL-OLD" in captured["system_prompt"]
        assert "MODEL-NEW" not in captured["system_prompt"]
        assert "CHANNEL-STYLE" not in captured["system_prompt"]
        assert llm_service.config.revision > initial_revision
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await llm_service.shutdown()
