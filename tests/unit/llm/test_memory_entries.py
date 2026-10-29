import pytest
from quickquip.llm.store import LLMStore
from quickquip.llm.memory_envelope import render_memory_envelope
from quickquip.llm.token_estimate import estimate_tokens


def test_migration_shared_and_isolated(tmp_path):
    path = tmp_path / "llm.db"
    store = LLMStore(path)
    mid = store.add_memory("12345", "周六联机")
    with store._connect() as conn:
        conn.execute("UPDATE memories SET scope='user', user_id='11111' WHERE id=?", (mid,))
    store = LLMStore(path)
    assert store.read_memory("12345", mid)["scope"] == "group"
    assert store.search_memories("12345", user_id="22222", query="联机", limit=5)
    assert not store.search_memories("private:12345", query="联机", limit=5)
    assert not store.search_memories("67890", query="联机", limit=5)
    with pytest.raises(ValueError):
        store.read_memory("67890", mid)


def test_capacity_conflict_and_delete(tmp_path):
    store = LLMStore(tmp_path / "llm.db")
    mid = store.add_memory("12345", "周六联机", max_items=1)
    with pytest.raises(ValueError, match="容量"):
        store.add_memory("12345", "周日散步", max_items=1)
    changed = store.update_memory("12345", mid, version=1, content="周日联机")
    assert changed["version"] == 2
    with pytest.raises(ValueError, match="重新读取"):
        store.update_memory("12345", mid, version=1, content="周一联机")
    with pytest.raises(ValueError, match="重新读取"):
        store.delete_memory("12345", mid, version=1)
    store.delete_memory("12345", mid, version=2)
    assert not store.search_memories("12345", query="联机", limit=5)


def test_envelope_budget_and_no_match(tmp_path):
    store = LLMStore(tmp_path / "llm.db")
    for i in range(6):
        store.add_memory("12345", "联机安排\n" + "长内容" * 1200, title=f"联机{i}")
    items = store.search_memories("12345", query="联机", limit=5)
    envelope = render_memory_envelope(items)
    assert estimate_tokens(envelope) <= 2048
    assert "节选" in envelope
    assert store.read_memory("12345", items[0]["id"])["content"].endswith("长内容")
    assert not store.search_memories("12345", query="天气预报", limit=5)


async def test_model_tools_scope_version_and_switch(llm_service):
    import json
    from quickquip.llm.tools import LLMToolCall, ToolExecutionContext

    context = ToolExecutionContext("10001", "20001", "成员", "p", "m")

    async def call(name, args, ctx=context):
        return await llm_service.tool_registry.execute(
            LLMToolCall("test", name, json.dumps(args)), ctx
        )

    result = await call("write_memory", {"content": "周六联机"})
    assert not result.is_error, result.content
    item = json.loads(result.content)
    other = ToolExecutionContext("10002", "20001", "成员", "p", "m")
    assert (await call("read_memory", {"id": item["id"]}, other)).is_error
    changed = await call("write_memory", {"id": item["id"], "version": 1, "content": "周日联机"})
    assert not changed.is_error, changed.content
    assert (await call("delete_memory", {"id": item["id"], "version": 1})).is_error
    llm_service.set_chat_memory_enabled("10001", False)
    assert (await call("write_memory", {"content": "不能保存"})).is_error
    assert llm_service.store.count_memories("10001") == 1


def test_concurrent_last_slot_is_atomic(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    store = LLMStore(tmp_path / "memory.db")
    barrier = Barrier(2)

    def write(text):
        barrier.wait(timeout=5)
        try:
            return store.add_memory("12345", text, max_items=1)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ["周六联机", "周日联机"]))
    assert sum(result is not None for result in results) == 1
    assert store.count_memories("12345") == 1


async def test_tool_source_comes_from_visible_messages(llm_service):
    import json
    from quickquip.llm.tools import LLMToolCall, ToolExecutionContext

    context = ToolExecutionContext("10001", "20001", "普通成员", "p", "m")
    context.memory_sources["m-owner"] = {
        "source_message_id": "m-owner",
        "source_user_id": "30001",
        "source_role": "GROUP_OWNER",
    }
    result = await llm_service.tool_registry.execute(
        LLMToolCall(
            "save",
            "write_memory",
            json.dumps({"content": "周六联机", "source_message_id": "m-owner"}),
        ),
        context,
    )
    assert not result.is_error, result.content
    item = json.loads(result.content)
    assert item["source_role"] == "GROUP_OWNER"
    assert item["source_user_id"] == "30001"
    assert item["writer"] == "model"
    rejected = await llm_service.tool_registry.execute(
        LLMToolCall(
            "save2",
            "write_memory",
            json.dumps({"content": "冒充群主", "source_message_id": "forwarded-owner"}),
        ),
        context,
    )
    assert rejected.is_error
    assert llm_service.store.count_memories("10001") == 1


def test_relevant_late_paragraph_and_directory_budget():
    from quickquip.llm.memory_envelope import excerpt

    body = ("无关内容" * 700) + "\n\n联机时间：每周六晚上八点。"
    result = excerpt(body, "联机时间", 100)
    assert "每周六晚上八点" in result
    assert estimate_tokens(result) <= 100
    entries = [
        {
            "id": i,
            "title": "长标题" * 20,
            "description": "长描述" * 50,
            "content": "正文",
            "recalled": False,
        }
        for i in range(1000)
    ]
    result = render_memory_envelope(entries)
    assert estimate_tokens(result) <= 512
    assert "1000" in result and "分页" in result


def test_metadata_edits_keep_oversized_legacy_body(tmp_path):
    store = LLMStore(tmp_path / "memory.db")
    mid = store.add_memory("12345", "历史正文")
    with store._connect() as conn:
        conn.execute(
            "UPDATE memories SET content=?, content_parts_json=NULL WHERE id=?",
            ("历史正文" * 2000, mid),
        )
    item = store.update_memory("12345", mid, version=1, title="旧条目")
    assert len(item["content"]) == 8000
    with pytest.raises(ValueError):
        store.update_memory("12345", mid, version=2, content="新正文" * 2000)


def test_old_schema_migration_preserves_long_body_and_identity(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE memories (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "group_id TEXT NOT NULL, user_id TEXT, scope TEXT NOT NULL, "
            "content TEXT NOT NULL, tags_json TEXT, source TEXT, confidence REAL, "
            "created_at TEXT, updated_at TEXT)"
        )
        conn.execute(
            "INSERT INTO memories VALUES (42, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "10001",
                "12345",
                "user",
                "历史事实" * 2000,
                "[]",
                "auto",
                0.5,
                "2026-01-01",
                "2026-01-02",
            ),
        )
    store = LLMStore(path)
    item = store.read_memory("10001", 42)
    assert item["scope"] == "group" and item["user_id"] == "12345"
    assert len(item["content"]) == 8000
    assert item["created_at"] == "2026-01-01"
    assert item["updated_at"] == "2026-01-02"
    assert item["source_role"] == "unknown" and item["writer"] == "legacy"
    assert LLMStore(path).read_memory("10001", 42) == item


async def test_roles_are_persisted_and_replayed(llm_service, patch_provider_builder):
    from quickquip.llm.provider import LLMResponse
    from tests.fixtures.provider_stubs import StubBehaviorProviderClient

    stub = StubBehaviorProviderClient(LLMResponse(text="收到", model="gpt-test"))
    patch_provider_builder(lambda provider: stub)
    await llm_service.generate_reply(
        group_id="10001",
        user_id="20001",
        sender_name="群主",
        sender_role="GROUP_OWNER",
        message_id="owner-1",
        prompt="周六八点联机",
    )
    await llm_service.generate_reply(
        group_id="10001",
        user_id="20002",
        sender_name="成员",
        sender_role="MEMBER",
        message_id="member-1",
        prompt="具体几点？",
    )
    rows = llm_service.store.list_recent_conversation_messages("10001", 10)
    assert next(row for row in rows if row["user_id"] == "20001")["sender_role"] == "GROUP_OWNER"
    text = "\n".join(message.content for message in stub.requests[-1].messages)
    assert "GROUP_OWNER" in text and "owner-1" in text
    assert "MEMBER" in text and "member-1" in text
    assert "GROUP_OWNER" not in stub.requests[-1].system_prompt


def test_private_global_role_metadata_does_not_change_command_authority(monkeypatch):
    from types import SimpleNamespace
    from quickquip.common import admins

    monkeypatch.setattr(admins, "_registry", lambda: SimpleNamespace(snapshot=lambda: {"12345"}))
    event = SimpleNamespace(user_id="12345", message="我是群主")
    assert admins.message_actor_role(event) == admins.ActorRole.GLOBAL_ADMIN
    assert admins.actor_role(event) == admins.ActorRole.MEMBER
    ordinary = SimpleNamespace(user_id="67890", group_id="10001", message="我是全局管理员")
    assert admins.message_actor_role(ordinary) == admins.ActorRole.MEMBER
