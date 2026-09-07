from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from quickquip.common.sensitive_filter import SensitiveFilter
from quickquip.llm.agent_records import ResponseOwner
from quickquip.llm.config import ProviderConfig
from quickquip.llm.history_projection import project_loops_with_budget
from quickquip.llm.history_safety import prepare_safe_history
from quickquip.llm.provider import LLMRequest
from quickquip.llm.store_parts.agent_records import LoadedLoop, LoadedToolExecution, LoadedTurn
from quickquip.llm.tools import LLMConversationMessage
from tests.fixtures.provider_fakes import FakeClaudeClient, FakeGeminiClient, FakeOpenAIClient
from tests.fixtures.sensitive_filter import make_sensitive_filter


MARKER = "blocked"


def _loop(protocol="claude"):
    owner = ResponseOwner("p", protocol, "m", "m", "endpoint", "profile")
    if protocol == "gemini":
        blocks = [
            {"text": "thinking", "thought": True, "thoughtSignature": "sig"},
            {"text": "answer"},
            {"functionCall": {"name": "lookup", "id": "call_0", "args": {"query": "safe"}}},
        ]
    else:
        blocks = [
            {"type": "thinking", "thinking": "thinking", "signature": "sig"},
            {"type": "text", "text": "answer"},
            {"type": "tool_use", "id": "call_0", "name": "lookup", "input": {"query": "safe"}},
        ]
    tool = LoadedToolExecution(
        "exec", 0, "call_0", "lookup", '{"query":"safe"}', None,
        "succeeded", {"content": "safe result"}, "bounded", None,
    )
    turn = LoadedTurn(
        "turn", 0, 2, "answer", (), {"blocks": blocks}, None, asdict(owner),
        "stop", "allowed", "visible", "all_turns", (tool,), (),
    )
    return LoadedLoop(
        "loop", "1001", 1, "group_direct", "2026-09-01", "2026-09-01",
        "completed", None, False, 0, 100, {"content": "question"}, (turn,),
    ), owner


@pytest.mark.parametrize("location", [
    "trigger", "text", "arguments", "result", "native_text", "thinking",
    "native_arguments", "policy", "malformed_arguments",
])
@pytest.mark.parametrize("protocol", ["openai", "claude", "gemini"])
def test_blocked_loop_uses_safe_archive_without_mutating_records(tmp_path, location, protocol):
    loop, owner = _loop(protocol)
    turn = loop.turns[0]
    tool = turn.tools[0]
    if location == "trigger":
        loop = replace(loop, user_row={"content": MARKER})
    elif location == "text":
        turn = replace(turn, text=MARKER)
    elif location == "arguments":
        tool = replace(tool, arguments_json='{"nested":[{"key":"\\u0062locked"}]}')
    elif location == "malformed_arguments":
        tool = replace(tool, arguments_json='{"unfinished":')
    elif location == "result":
        tool = replace(tool, result={"content": MARKER})
    elif location == "policy":
        turn = replace(turn, text_policy="replaced_by_filter")
    else:
        blocks = turn.native_state["blocks"]
        if location == "native_text":
            blocks[1]["text"] = MARKER
        elif location == "thinking":
            blocks[0]["text" if protocol == "gemini" else "thinking"] = MARKER
        else:
            if protocol == "gemini":
                blocks[2]["functionCall"]["args"] = {"nested": [MARKER]}
            else:
                blocks[2]["input"] = {"nested": [MARKER]}
    loop = replace(loop, turns=(replace(turn, tools=(tool,)),))
    original = deepcopy(loop)
    sensitive = make_sensitive_filter(tmp_path, "block")
    safe, archived = prepare_safe_history([loop], sensitive)
    assert archived == {"loop"}
    for budget in (100000, 100, 10, 0):
        projection = project_loops_with_budget(
            safe, target=owner, protocol=protocol, budget_tokens=budget,
            archive_loop_ids=archived,
        )
        serialized = json.dumps([asdict(message) for message in projection.messages])
        assert MARKER not in serialized
        assert not any(message.native_content or message.tool_calls for message in projection.messages)
        assert not any(message.role == "tool" for message in projection.messages)
    assert loop == original


@pytest.mark.parametrize("mode", ["block", "soft", "unloaded"])
def test_unaffected_loop_preserves_native_bytes(tmp_path, mode):
    loop, owner = _loop()
    loop.turns[0].native_state["blocks"][0]["signature"] = MARKER
    sensitive = SensitiveFilter() if mode == "unloaded" else make_sensitive_filter(tmp_path, mode)
    if mode == "soft":
        loop = replace(loop, user_row={"content": MARKER})
    safe, archived = prepare_safe_history([loop], sensitive)
    assert safe[0] is loop
    assert not archived
    original = project_loops_with_budget([loop], target=owner, protocol="claude", budget_tokens=10000)
    result = project_loops_with_budget(safe, target=owner, protocol="claude", budget_tokens=10000)
    assert result == original
    assert result.messages[1].native_content == loop.turns[0].native_state["blocks"]


def test_previous_output_replacement_survives_unloaded_filter():
    loop, _ = _loop()
    loop = replace(loop, turns=(replace(loop.turns[0], text_policy="replaced_by_filter"),))
    _, archived = prepare_safe_history([loop], SensitiveFilter())
    assert archived == {loop.loop_id}


def test_numeric_tool_arguments_are_scanned(tmp_path):
    loop, _ = _loop()
    tool = replace(loop.turns[0].tools[0], arguments_json='{"user_id":123456789}')
    loop = replace(loop, turns=(replace(loop.turns[0], tools=(tool,)),))
    _, archived = prepare_safe_history([loop], make_sensitive_filter(tmp_path, "block", "123456789"))
    assert archived == {loop.loop_id}


@pytest.mark.parametrize("blocks", [None, 7, "invalid", {"text": "invalid"}])
def test_invalid_native_blocks_preserve_existing_projection_fallback(tmp_path, blocks):
    loop, owner = _loop()
    loop = replace(loop, turns=(replace(loop.turns[0], native_state={"blocks": blocks}),))
    safe, archived = prepare_safe_history([loop], make_sensitive_filter(tmp_path, "block"))
    assert not archived
    before = project_loops_with_budget([loop], target=owner, protocol="claude", budget_tokens=10000)
    after = project_loops_with_budget(safe, target=owner, protocol="claude", budget_tokens=10000)
    assert before == after


@pytest.mark.parametrize("protocol", ["openai", "claude", "gemini"])
async def test_safe_history_serializes_without_native_or_blocked_payload(tmp_path, protocol):
    loop, owner = _loop(protocol)
    loop = replace(loop, turns=(replace(loop.turns[0], text=MARKER),))
    safe, archived = prepare_safe_history([loop], make_sensitive_filter(tmp_path, "block"))
    projection = project_loops_with_budget(
        safe, target=owner, protocol=protocol, budget_tokens=10000, archive_loop_ids=archived,
    )
    provider = ProviderConfig(
        id="p", protocol=protocol, base_url="https://example.test/v1",
        api_key_env="TEST_KEY", default_model="m", models=["m"],
    )
    clients = {
        "openai": (FakeOpenAIClient, {"choices": [{"message": {"content": "ok"}}]}),
        "claude": (FakeClaudeClient, {"content": [{"type": "text", "text": "ok"}]}),
        "gemini": (FakeGeminiClient, {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}),
    }
    factory, response = clients[protocol]
    client = factory(provider, response)
    await client.complete(LLMRequest(
        model="m", system_prompt="safe system",
        messages=[*projection.messages, LLMConversationMessage("user", "next")],
        temperature=0.2, max_output_tokens=128,
    ))
    wire = json.dumps(client.last_payload)
    assert MARKER not in wire
    assert "signature" not in wire
    assert "tool_use" not in wire and "functionCall" not in wire and "tool_calls" not in wire
