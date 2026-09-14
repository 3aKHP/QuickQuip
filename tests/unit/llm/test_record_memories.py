
import pytest

from quickquip.common.identity import IdentityEntry
from quickquip.common.record_content import legacy, references
from quickquip.llm.store import LLMStore


from tests.fixtures.record_identities import snapshot as snapshot
from tests.fixtures.record_identities import index

def test_memory_legacy_matching_scope_and_delete(tmp_path, snapshot):
    store = LLMStore(tmp_path / "llm.db")
    body = legacy("[CQ:at,qq=12345,name=旧名] 的事实")
    member_id = store.add_memory("10001", "", content_parts=body)
    own = store.add_memory("10001", "个人事实无需出现名字", scope="user", user_id="12345")
    store.add_memory("10001", "他人的私密事实", scope="user", user_id="23456", content_parts=body)
    with store._connect() as conn:
        conn.execute(
            "UPDATE memories SET content_parts_json=NULL, "
            "content='[CQ:at,name=旧名,qq=12345] 历史' WHERE id=?", (member_id,)
        )
    rows = store.list_memories("10001", keyword="别名")
    assert len(rows) == 3
    assert rows[-1]["content_display"] == "@标准名 历史"
    assert "[CQ:at" in rows[-1]["content"]
    for query in ("别名", "标准名", "12345", "[CQ:at,name=旧名,qq=12345]"):
        hits = store.search_memories("10001", user_id="12345", query=query, limit=10)
        assert {r["id"] for r in hits} == {own, member_id}
    assert [
        r["id"]
        for r in store.search_memories("10001", user_id="12345", query="", limit=1, scope="user")
    ] == [own]
    assert store.delete_memories("10001", f"#{member_id}") == 1
    with store._connect() as conn:
        assert not conn.execute(
            "SELECT * FROM memories_member_refs WHERE record_id=?", (member_id,)
        ).fetchall()
    snapshot.index = index(
        IdentityEntry("同名", ["12345"], [], ""), IdentityEntry("同名", ["23456"], [], "")
    )
    with pytest.raises(ValueError, match="12345"):
        store.delete_memories("10001", "同名")
    store.clear_memories("10001")
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM memories_member_refs").fetchone()[0] == 0


async def test_memory_tool_does_not_expand_personal_scope(tmp_path, snapshot):
    from quickquip.llm.service_parts.tools import ToolMixin
    from quickquip.llm.service_parts.scope import ScopeMixin
    from quickquip.llm.tools import ToolExecutionContext
    class Service(ToolMixin, ScopeMixin):
        pass
    service = Service()
    service.store = LLMStore(tmp_path / "llm.db")
    service.store.add_memory("10001", "", content_parts=legacy("[CQ:at,qq=12345] 群事实"))
    service.store.add_memory("10001", "本人事实", scope="user", user_id="23456")
    service.store.add_memory("10001", "其他成员私密", scope="user", user_id="12345")
    context = ToolExecutionContext("10001", "23456", "卡", "provider", "model")
    result = await service._tool_list_memories({"keyword": "12345"}, context)
    assert "@标准名 群事实" in result
    assert "其他成员私密" not in result


async def test_auto_memory_projection_preserves_history_and_model_strings(
    llm_service, snapshot, monkeypatch
):
    monkeypatch.setattr(llm_service._identity_repository, "snapshot", lambda scope: snapshot)
    scope = "10001"
    historical = "[CQ:at,name=旧称呼,qq=23456] 的历史提及"
    literal = "代码示例 [CQ:at,qq=23456] 保持原文"
    llm_service.store.append_conversation_message(
        scope, "12345", "user", historical, raw_content=historical,
        canonical_name="旧标准", sender_name="旧卡",
    )
    llm_service.store.append_conversation_message(
        scope, "12345", "user", literal, raw_content=literal,
        canonical_name="旧标准", sender_name="旧卡",
    )
    before = llm_service.store.list_recent_conversation_messages(scope, 10)
    prompts = []
    async def judge(prompt, **kwargs):
        prompts.append(prompt)
        return '{"memories": ["模型写出的小明喜欢编程"]}'
    monkeypatch.setattr(llm_service, "quick_judge", judge)
    llm_service._auto_memory_turns[scope] = 9
    await llm_service._extract_auto_memory(
        scope_key=scope, user_id="12345", sender_name="旧卡", canonical_name="旧标准",
        user_text=literal,
        assistant_text="收到，我会根据当前发言和近期语境判断是否值得记住这些信息。",
    )
    assert "标准名（QQ 12345）" in prompts[0]
    assert "@未登记名片 的历史提及" in prompts[0]
    assert literal in prompts[0]
    record = llm_service.store.list_memories(scope)[0]
    assert record["user_id"] == "12345" and record["scope"] == "user"
    assert record["content"] == "模型写出的小明喜欢编程"
    assert not references(record["content_parts"])
    assert llm_service.store.list_recent_conversation_messages(scope, 10) == before



def test_multi_account_identity_is_not_a_homonym(tmp_path, snapshot):
    from quickquip.common.record_content import legacy
    snapshot.index = index(IdentityEntry("同一人", ["12345", "34567"], [], ""))
    store = LLMStore(tmp_path / "memories.db")
    for qq in ("12345", "34567"):
        store.add_memory("10001", "", content_parts=legacy(f"[CQ:at,qq={qq}] 事实"))
    assert snapshot.candidates("12345") == {"12345"}
    assert store.delete_memories("10001", "12345") == 1
    store.add_memory("10001", "", content_parts=legacy("[CQ:at,qq=12345] 事实"))
    assert store.delete_memories("10001", "同一人") == 2


def test_service_identity_assignment_uses_repository_owner(llm_service):
    replacement = index(IdentityEntry("手动身份", ["34567"], [], ""))
    llm_service.identities = replacement
    assert llm_service.identities is replacement
    assert llm_service.group_identities("10001").resolve_user("34567").canonical_name == "手动身份"
    assert llm_service.store.identity_repository is llm_service._identity_repository
    llm_service.reload_config()
    assert llm_service.identities.resolve_user("34567").canonical_name == ""
