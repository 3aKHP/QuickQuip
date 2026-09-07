"""Current word lists apply to complete tool history in group and private replies."""
from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from quickquip.llm.provider import LLMResponse
from quickquip.llm.tools import LLMToolCall
from tests.fixtures.sensitive_filter import make_sensitive_filter


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("with_tool", [False, True])
async def test_updated_filter_scrubs_complete_history(
    llm_service, tmp_path, monkeypatch, patch_provider_builder, private, with_tool,
):
    marker = "NEWLYBLOCKEDMARKER"
    requests = []

    class Client:
        answer = marker

        async def complete(self, request):
            requests.append(request)
            if with_tool and len(requests) == 1:
                return LLMResponse(
                    text="Checking identity", model=request.model,
                    tool_calls=[LLMToolCall("call_1", "get_identity", '{"query":"2002"}')],
                )
            return LLMResponse(text=self.answer, model=request.model)

    client = Client()
    patch_provider_builder(lambda provider: client)
    sensitive = make_sensitive_filter(tmp_path, "block", "unrelatedword")
    monkeypatch.setattr("quickquip.llm.service._get_sensitive_filter", lambda: sensitive)
    if private:
        llm_service.start_private_session(2002)

    async def reply(prompt):
        kwargs = dict(user_id=2002, sender_name="Test", prompt=prompt, trigger_auto_memory=False)
        if private:
            return await llm_service.generate_private_reply(**kwargs)
        return await llm_service.generate_reply(group_id=1001, **kwargs)

    assert (await reply("First question"))["reply"] == marker
    scope = "private:2002" if private else "1001"
    before = llm_service.store.list_recent_conversation_messages(scope, limit=50)
    sensitive = make_sensitive_filter(tmp_path, "block", marker)
    client.answer = "safe reply"
    await reply("Second question")
    assert marker not in json.dumps(asdict(requests[-1]), ensure_ascii=False)
    after = llm_service.store.list_recent_conversation_messages(scope, limit=50)
    assert all(row in after for row in before)
