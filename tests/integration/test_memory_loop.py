"""主服务在工具写入后保留本轮记忆快照，下轮读取最新条目。"""

from copy import deepcopy
import json

from quickquip.llm.provider import LLMResponse
from quickquip.llm.tools import LLMToolCall


async def test_service_memory_write_preserves_loop_prefix(llm_service, patch_provider_builder):
    mid = llm_service.remember_memory("10001", "旧安排：周六八点联机")
    llm_service.config.tools.discovery_mode = "off"
    requests = []

    class Client:
        async def complete(self, request):
            requests.append(deepcopy(request))
            if len(requests) == 1:
                return LLMResponse(
                    model=request.model,
                    text="",
                    finish_reason="tool_calls",
                    tool_calls=[
                        LLMToolCall(
                            "save",
                            "write_memory",
                            json.dumps(
                                {
                                    "id": mid,
                                    "version": 1,
                                    "content": "新安排：周日九点联机",
                                    "source_message_id": "request-1",
                                }
                            ),
                        )
                    ],
                )
            return LLMResponse(model=request.model, text="已更新", finish_reason="stop")

    patch_provider_builder(lambda provider: Client())
    await llm_service.generate_reply(
        group_id="10001",
        user_id="20001",
        sender_name="群主",
        sender_role="GROUP_OWNER",
        message_id="request-1",
        prompt="请调整联机安排",
    )
    assert len(requests) == 2
    first = requests[0]
    assert "旧安排：周六八点联机" in first.messages[-1].content
    assert "角色：GROUP_OWNER" in first.messages[-1].content
    assert "角色：unknown" not in first.messages[-1].content
    assert requests[1].messages[: len(first.messages)] == first.messages
    assert requests[1].system_prompt == first.system_prompt
    saved = llm_service.store.read_memory("10001", mid)
    assert saved["content"] == "新安排：周日九点联机" and saved["version"] == 2
    assert saved["source_message_id"] == "request-1"
    assert saved["source_role"] == "GROUP_OWNER"
    await llm_service.generate_reply(
        group_id="10001",
        user_id="20002",
        sender_name="成员",
        sender_role="MEMBER",
        message_id="request-2",
        prompt="联机现在怎么安排？",
    )
    assert "新安排：周日九点联机" in requests[-1].messages[-1].content
