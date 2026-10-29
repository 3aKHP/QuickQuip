import json

import pytest

from quickquip.llm.memory_envelope import excerpt
from quickquip.llm.store import LLMStore
from quickquip.llm.token_estimate import estimate_tokens
from quickquip.llm.tools import LLMToolCall, ToolExecutionContext


async def query(service, arguments, *, chat_type="group"):
    result = await service.tool_registry.execute(
        LLMToolCall("lookup", "list_memories", json.dumps(arguments)),
        ToolExecutionContext("10001", "20001", "成员", "p", "m", chat_type=chat_type),
    )
    assert not result.is_error, result.content
    return json.loads(result.content)


async def test_question_search_ranks_and_excerpts_with_scope_isolation(llm_service):
    store = llm_service.store
    body = "说明事项。" * 400 + "\n\n星河联机安排：周六晚上八点集合。"
    wanted = store.add_memory("10001", body, title="星河联机", description="集合时间")
    weaker = store.add_memory("10001", "星河书单已更新")
    store.add_memory("10001", "早餐供应豆浆")
    private = store.add_memory("private:10001", "星河联机在私聊中约定")
    store.add_memory("10002", "星河联机在另一个群约定")

    result = await query(llm_service, {"keyword": "星河联机什么时候集合"})
    assert [item["id"] for item in result["items"]] == [wanted, weaker]
    assert result["total"] == 3 and result["matched_count"] == 2
    assert result["next_offset"] is None
    first = result["items"][0]
    assert "周六晚上八点" in first["excerpt"]
    assert estimate_tokens(first["excerpt"]) <= 128
    assert "content" not in first
    full = await llm_service.tool_registry.execute(
        LLMToolCall("read", "read_memory", json.dumps({"id": wanted})),
        ToolExecutionContext("10001", "20001", "成员", "p", "m"),
    )
    assert not full.is_error, full.content
    assert json.loads(full.content)["content"] == body

    result = await query(llm_service, {"keyword": "星河联机"}, chat_type="private")
    assert [item["id"] for item in result["items"]] == [private]
    empty = await query(llm_service, {"keyword": "天气预报"})
    assert empty == {"total": 3, "matched_count": 0, "next_offset": None, "items": []}


async def test_search_pages_cover_matches_and_blank_query_browses_latest(llm_service):
    # One more match than the tool's 20-entry page exercises the continuation.
    ids = [llm_service.store.add_memory("10001", "星河联机周六集合") for _ in range(21)]
    newest = llm_service.store.add_memory("10001", "今天早餐吃面包")
    first = await query(llm_service, {"keyword": "星河联机什么时候集合"})
    second = await query(llm_service, {"keyword": "星河联机什么时候集合", "offset": 20})
    assert first["next_offset"] == 20 and second["next_offset"] is None
    assert first["matched_count"] == second["matched_count"] == 21
    assert [item["id"] for item in first["items"] + second["items"]] == ids
    beyond = await query(llm_service, {"keyword": "星河联机", "offset": 40})
    assert beyond["items"] == [] and beyond["next_offset"] is None

    directory = await query(llm_service, {"keyword": "  "})
    assert [item["id"] for item in directory["items"]] == [newest] + ids[::-1][:19]
    assert directory["total"] == directory["matched_count"] == 22
    assert directory["next_offset"] == 20
    assert all("excerpt" not in item for item in directory["items"])


@pytest.mark.parametrize("field", ["title", "description"])
def test_short_literal_metadata_match_is_not_lost(tmp_path, field):
    store = LLMStore(tmp_path / "memory.db")
    wanted = store.add_memory("10001", "出门随身携带物品", **{field: "伞"})
    assert [item["id"] for item in store.search_memories(
        "10001", query="伞", limit=None
    )] == [wanted]


@pytest.mark.parametrize("separator", ["\n\n", ""])
def test_single_character_query_excerpts_late_literal_match(separator):
    text = "晴朗的日子。" * 400 + separator + "伞放在门口。"
    result = excerpt(text, "伞", 128)
    assert "伞放在门口" in result
    assert estimate_tokens(result) <= 128
