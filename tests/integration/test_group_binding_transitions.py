"""Group settings writes affect the next reply while in-flight requests stay frozen."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from quickquip.adapters.nonebot.command_parts import llm as commands
from quickquip.app.web.routes import group_settings as routes
from quickquip.llm.provider import LLMResponse
from quickquip.llm.service import LLMService
from tests.fixtures.configs import MIN_LLM_CONFIG_TOML, write_llm_config_bundle


class CommandFinished(Exception):
    pass


class Command:
    def handle(self):
        def register(handler):
            self.handler = handler
            return handler
        return register

    async def finish(self, message):
        raise CommandFinished(message)


@pytest.fixture
def binding_service(tmp_path):
    toml = MIN_LLM_CONFIG_TOML + '''

[[providers]]
id = "alternate"
protocol = "openai"
base_url = "https://alternate.example.test/v1"
api_key_env = "TEST_ALTERNATE_KEY"
default_model = "alternate-model"
models = ["alternate-model"]

[[personas]]
id = "alternate-persona"
display_name = "另一人格"
system_prompt = "你是另一个测试人格。"
'''
    return LLMService(**write_llm_config_bundle(tmp_path, config_toml=toml))


@pytest.mark.parametrize("write_path", ["web", "command"])
async def test_group_binding_switch_preserves_inflight_and_other_group(
    binding_service, monkeypatch, patch_provider_builder, write_path,
):
    service = binding_service
    entered = asyncio.Event()
    release = asyncio.Event()
    requests = []

    def build_client(provider):
        async def complete(request):
            requests.append((provider.id, request))
            if len(requests) == 1:
                entered.set()
                await release.wait()
            return LLMResponse(text="测试回复", model=request.model, finish_reason="stop")
        return SimpleNamespace(complete=complete)

    patch_provider_builder(build_client)

    async def reply(group_id):
        return await service.generate_reply(
            group_id=group_id, user_id=2002, sender_name="测试用户",
            prompt="你好", recent_messages=[],
        )

    old_reply = asyncio.create_task(reply(10001))
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        if write_path == "web":
            monkeypatch.setattr(routes, "_DB", service.store.path)
            monkeypatch.setattr(routes, "get_config_service", lambda: service.config_service)
            monkeypatch.setattr(routes.audit_logger, "log", lambda *args, **kwargs: None)
            result = routes.put_group_settings(
                "10001", routes.GroupSettingsBody(
                    provider_id="alternate", model="alternate-model",
                    persona_id="alternate-persona",
                ), object(),
            )
            assert result == {"ok": True}
        else:
            cmd = Command()
            commands.register_llm_commands(
                lambda name, **kwargs: cmd if name == "llm" else Command(), list, object(),
            )
            monkeypatch.setattr(commands, "_ensure_llm_bindings", lambda: None)
            monkeypatch.setattr(commands, "get_llm_service", lambda: service)
            for text in ("/llm use alternate alternate-model",
                         "/llm persona use alternate-persona"):
                event = SimpleNamespace(
                    message_type="group", group_id=10001, user_id=2002,
                    sender=SimpleNamespace(role="admin"), get_message=lambda text=text: text,
                )
                with pytest.raises(CommandFinished, match="切换"):
                    await cmd.handler(event)

        settings = service.get_group_settings(10001)
        assert (settings.provider_id, settings.model, settings.persona_id) == (
            "alternate", "alternate-model", "alternate-persona",
        )
        release.set()
        assert (await asyncio.wait_for(old_reply, timeout=10))["llm_used"]
        assert (await reply(10001))["llm_used"]
        assert (await reply(10002))["llm_used"]
    finally:
        release.set()
        if not old_reply.done():
            old_reply.cancel()
        await asyncio.gather(old_reply, return_exceptions=True)

    assert [(pid, request.model) for pid, request in requests] == [
        ("openai-main", "gpt-test"),
        ("alternate", "alternate-model"),
        ("openai-main", "gpt-test"),
    ]
    default_prompt = service.config.personas["default"].system_prompt
    alternate_prompt = service.config.personas["alternate-persona"].system_prompt
    assert default_prompt in requests[0][1].system_prompt
    assert alternate_prompt not in requests[0][1].system_prompt
    assert alternate_prompt in requests[1][1].system_prompt
    assert default_prompt not in requests[1][1].system_prompt
    assert default_prompt in requests[2][1].system_prompt
    assert alternate_prompt not in requests[2][1].system_prompt
