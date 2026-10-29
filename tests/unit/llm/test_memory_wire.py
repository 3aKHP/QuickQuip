"""四协议的记忆注入位置与同轮文本快照。网络边界使用假客户端。"""

from copy import deepcopy
import json

import pytest

from quickquip.llm.provider import LLMRequest
from quickquip.llm.tools import LLMConversationMessage, LLMToolCall
from quickquip.llm.memory_envelope import render_memory_envelope
from tests.fixtures.provider_fakes import (
    FakeOpenAIClient,
    FakeClaudeClient,
    FakeGeminiClient,
    FakeOpenAIResponsesClient,
)
from tests.unit.llm.test_provider_openai import _provider_config as openai_config
from tests.unit.llm.test_provider_claude import _provider_config as claude_config
from tests.unit.llm.test_provider_gemini import _provider_config as gemini_config
from tests.unit.llm.test_provider_openai_responses import _config as responses_config


def cache_text(value):
    # cache_control 指定服务端断点，本身不属于输入文本。
    if isinstance(value, dict):
        return {k: cache_text(v) for k, v in value.items() if k != "cache_control"}
    if isinstance(value, list):
        return [cache_text(v) for v in value]
    return value


@pytest.mark.parametrize("protocol", ["openai", "claude", "gemini", "openai_responses"])
async def test_recall_changes_only_tail_and_loop_reuses_snapshot(protocol, llm_service):
    factories = {
        "openai": (FakeOpenAIClient, openai_config, {"choices": [{"message": {"content": "ok"}}]}),
        "claude": (
            FakeClaudeClient,
            claude_config,
            {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"},
        ),
        "gemini": (
            FakeGeminiClient,
            gemini_config,
            {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        ),
        "openai_responses": (
            FakeOpenAIResponsesClient,
            responses_config,
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "ok"}],
                    }
                ],
            },
        ),
    }
    cls, config, response = factories[protocol]
    client = cls(config(), [response] * 3 if protocol == "openai_responses" else response)
    mid = llm_service.store.add_memory("10001", "每周六联机")
    history = [
        LLMConversationMessage("user", "先前问题"),
        LLMConversationMessage("assistant", "先前回答"),
    ]
    snapshot = render_memory_envelope([llm_service.store.read_memory("10001", mid)])
    current = LLMConversationMessage("user", snapshot + "\n什么时候联机？")

    async def send(messages):
        await client.complete(
            LLMRequest(
                model=config().default_model,
                system_prompt="固定人格与记忆规则",
                messages=messages,
                temperature=0.2,
                max_output_tokens=128,
                tools=llm_service.tool_registry.get_specs(
                    ["list_memories", "read_memory", "write_memory", "delete_memory"]
                ),
                allow_tool_calls=True,
            )
        )
        return deepcopy(
            client.payloads[-1] if protocol == "openai_responses" else client.last_payload
        )

    first = await send(history + [current])
    if protocol == "openai_responses":
        # Responses may make optional fields required when strict is omitted.
        for tool in first["tools"]:
            assert tool["strict"] is False
        write = next(tool for tool in first["tools"] if tool["name"] == "write_memory")
        assert "content_parts" not in write["parameters"].get("required", [])
        assert "id" not in write["parameters"].get("required", [])
    llm_service.store.update_memory("10001", mid, version=1, content="每周日联机")
    changed = render_memory_envelope([llm_service.store.read_memory("10001", mid)])
    second = await send(history + [LLMConversationMessage("user", changed + "\n什么时候联机？")])
    key = {"gemini": "contents", "openai_responses": "input"}.get(protocol, "messages")
    assert cache_text(first[key][:-1]) == cache_text(second[key][:-1])
    for static in ("system", "instructions", "systemInstruction", "tools"):
        assert first.get(static) == second.get(static)
    loop = await send(
        history
        + [
            current,
            LLMConversationMessage(
                "assistant",
                tool_calls=[LLMToolCall("read1", "read_memory", json.dumps({"id": mid}))],
            ),
            LLMConversationMessage(
                "tool", "每周日联机", tool_call_id="read1", tool_name="read_memory"
            ),
        ]
    )
    assert cache_text(loop[key][: len(first[key])]) == cache_text(first[key])
    assert "每周六联机" in json.dumps(loop[key], ensure_ascii=False)
