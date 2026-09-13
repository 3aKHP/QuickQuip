from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import runpy
import sqlite3

import pytest

from quickquip.app.identities import IdentityRepository, IdentitySnapshot, identities, web_identities
from quickquip.common.identity import IdentityEntry, IdentityIndex
from quickquip.common.record_content import decode, from_segments, legacy, matches, migrate, plain, references, render, validate
from quickquip.chat.group_quotes import GroupQuoteStore
from quickquip.chat.offline_messages import OfflineMessageStore
from quickquip.llm.store import LLMStore


def index(*entries):
    result = IdentityIndex(entries=list(entries))
    result._build_indexes()
    return result


@pytest.fixture
def snapshot(monkeypatch):
    snap = IdentitySnapshot(index(IdentityEntry("标准名", ["12345"], ["别名"], "")), {"12345": "名片", "23456": "未登记名片"})
    monkeypatch.setattr(identities, "snapshot", lambda scope: snap)
    monkeypatch.setattr(web_identities, "snapshot", lambda scope: snap)
    return snap


def test_protocol_boundaries(snapshot):
    raw = "[CQ:at,name=旧&#44;名&amp;,extra=1,qq=12345] 喜欢 [CQ:image,file=x] @QQ23456"
    body = legacy(raw)
    assert references(body) == {"12345", "23456"}
    assert render(body, snapshot) == "@标准名 喜欢 [图片] @未登记名片"
    assert body["parts"][1]["name"] == "旧,名&"
    assert render(legacy("12345 @名字 abc@QQ12345 @QQ12345abc [CQ:at,qq=no]"), snapshot) == "12345 @名字 abc@QQ12345 @QQ12345abc [CQ:at,qq=no]"
    literal = from_segments([{"type": "text", "data": {"text": raw}}])
    assert render(literal, snapshot) == raw
    assert references(literal) == set()


def test_command_only_stripped_from_text_segment(snapshot):
    message = [{"type": "text", "data": {"text": "/remember "}}, {"type": "at", "data": {"qq": "12345", "name": "旧名"}}, {"type": "text", "data": {"text": " /remember 保留"}}, {"type": "at", "data": {"qq": "all"}}, {"type": "at", "data": {"qq": "99999", "name": "机器人"}}]
    assert render(from_segments(message, "remember"), snapshot) == "@标准名 /remember 保留@全体成员@机器人"
    assert render(from_segments(message), snapshot).startswith("/remember ")


@pytest.mark.parametrize("part", [{"type": "member", "qq": "all"}, {"type": "member", "qq": 12345}, {"type": "member", "qq": "12345", "usage": "bad"}, {"type": "member", "qq": "12345", "name": []}, {"type": "member", "qq": "12345", "usage": []}, {"type": "media", "media": []}, {"type": "media", "media": "bad"}, {"type": "text", "text": None}])
def test_validation_rejects_invalid_parts(part):
    with pytest.raises(ValueError):
        validate({"version": 1, "parts": [part]})


def test_validation_enforces_length():
    with pytest.raises(ValueError):
        validate(plain("x" * 4097))


def test_identity_merge_and_ambiguous_names():
    global_index = index(IdentityEntry("同名", ["12345"], [], ""), IdentityEntry("同名", ["23456"], [], ""))
    group = index(IdentityEntry("群标准名", ["12345"], ["旧别名"], ""))
    snap = IdentitySnapshot(global_index.merge(group))
    assert snap.name("12345") == "群标准名"
    assert snap.name("23456") == "同名"
    assert len(global_index.search("同名")) == 2
    assert IdentitySnapshot(global_index).candidates("同名") == {"12345", "23456"}


def write_identity(path, name):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'people:\n  - canonical_name: "{name}"\n    qq_ids: ["12345"]\n', encoding="utf-8")


def test_repository_refresh_failure_and_scope_isolation(tmp_path, monkeypatch):
    import quickquip.common.identity_sources as module
    now = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    path = tmp_path / "identities.yaml"
    write_identity(path, "全局")
    write_identity(tmp_path / "10001" / "identities.yaml", "本群")
    stats = tmp_path / "stats.json"
    stats.write_text(json.dumps({"10001": {"user_names": {"23456": "本群卡"}}}))
    repo = IdentityRepository(path, stats)
    assert repo.snapshot("10001").name("12345") == "本群"
    assert repo.snapshot("10002").name("12345") == "全局"
    assert repo.snapshot("private:10001").name("23456") == "QQ23456"
    write_identity(path, "更新")
    assert repo.snapshot("10002").name("12345") == "全局"
    now[0] += 5
    assert repo.snapshot("10002").name("12345") == "更新"
    path.write_text("people: [broken")
    now[0] += 5
    assert repo.snapshot("10002").name("12345") == "更新"
    write_identity(path, "reload")
    repo.invalidate()
    assert repo.snapshot("10002").name("12345") == "reload"


def test_memory_legacy_matching_scope_and_delete(tmp_path, snapshot):
    store = LLMStore(tmp_path / "llm.db")
    body = legacy("[CQ:at,qq=12345,name=旧名] 的事实")
    member_id = store.add_memory("10001", "", content_parts=body)
    own = store.add_memory("10001", "个人事实无需出现名字", scope="user", user_id="12345")
    store.add_memory("10001", "他人的私密事实", scope="user", user_id="23456", content_parts=body)
    with store._connect() as conn:
        conn.execute("UPDATE memories SET content_parts_json=NULL, content='[CQ:at,name=旧名,qq=12345] 历史' WHERE id=?", (member_id,))
    rows = store.list_memories("10001", keyword="别名")
    assert len(rows) == 3
    assert rows[-1]["content_display"] == "@标准名 历史"
    assert "[CQ:at" in rows[-1]["content"]
    for query in ("别名", "标准名", "12345", "[CQ:at,name=旧名,qq=12345]"):
        hits = store.search_memories("10001", user_id="12345", query=query, limit=10)
        assert {r["id"] for r in hits} == {own, member_id}
    assert [r["id"] for r in store.search_memories("10001", user_id="12345", query="", limit=1, scope="user")] == [own]
    assert store.delete_memories("10001", f"#{member_id}") == 1
    with store._connect() as conn:
        assert not conn.execute("SELECT * FROM memories_member_refs WHERE record_id=?", (member_id,)).fetchall()
    snapshot.index = index(IdentityEntry("同名", ["12345"], [], ""), IdentityEntry("同名", ["23456"], [], ""))
    with pytest.raises(ValueError, match="12345"):
        store.delete_memories("10001", "同名")
    store.clear_memories("10001")
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM memories_member_refs").fetchone()[0] == 0


def test_quote_pagination_mentions_and_author_separate(tmp_path, snapshot):
    store = GroupQuoteStore(tmp_path / "quotes.db")
    for i in range(7):
        store.add("10001", "23456", "旧作者", str(i), "99999", content_parts=legacy(f"[CQ:at,qq=12345,name=旧名] {i}"))
    store.add("10001", "12345", "旧作者", "没有提及", "99999")
    with store._db:
        store._db.execute("UPDATE quotes SET content_parts_json=NULL, content='[CQ:at,qq=12345,name=旧名] 0' WHERE id=1")
    rows, total = store.search("10001", "标准名", offset=2, limit=2)
    assert total == 7 and [r["id"] for r in rows] == [5, 4]
    assert all("@标准名" in r["content_display"] for r in rows)
    authors, total = store.search_by_sender("10001", user_ids=["12345"])
    assert total == 1 and authors[0]["content"] == "没有提及"
    store.delete(5)
    assert not store._db.execute("SELECT * FROM quotes_member_refs WHERE record_id=5").fetchall()
    store.close()


def test_offline_retains_mentions_and_plain_display(tmp_path, snapshot):
    store = OfflineMessageStore(tmp_path / "offline.db")
    store.add("10001", "12345", "旧发送者", "23456", "", content_parts=legacy("[CQ:at,qq=12345] [CQ:at,qq=all] [CQ:record,file=x]"))
    pending = store.list_pending_for("10001", "23456")
    assert "[标准名 " in pending[0].format_display()
    assert "@标准名 @全体成员 [语音]" in pending[0].format_display()
    assert store.pop_pending("10001", "23456")[0].format_display() == pending[0].format_display()
    assert not store._db.execute("SELECT * FROM offline_messages_member_refs").fetchall()
    store.close()


def test_concurrent_first_migration(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE memories(id INTEGER PRIMARY KEY, group_id TEXT, content TEXT)")
    def worker(_):
        with sqlite3.connect(path) as conn:
            migrate(conn, "memories")
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(worker, range(12)))
    with sqlite3.connect(path) as conn:
        assert len([r for r in conn.execute("PRAGMA table_info(memories)") if r[1] == "content_parts_json"]) == 1


def test_backfill_preview_repeat_race_backup_and_match_parity(tmp_path, snapshot):
    backfill = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/backfill_record_identities.py"))["backfill"]
    path = tmp_path / "old.db"
    raw = "[CQ:at,name=旧名,qq=12345] 的事实"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE memories(id INTEGER PRIMARY KEY, group_id TEXT, content TEXT)")
        conn.executemany("INSERT INTO memories VALUES (?, '10001', ?)", [(1, raw), (2, raw)])
    preview = backfill(path, "memories")
    assert preview["convertible"] == 2
    assert not list(tmp_path.glob("*.bak"))
    with sqlite3.connect(path) as conn:
        assert "content_parts_json" not in [r[1] for r in conn.execute("PRAGMA table_info(memories)")]
    def race(row):
        if row["id"] == 2:
            with sqlite3.connect(path) as conn:
                conn.execute("UPDATE memories SET content='edited' WHERE id=2")
    result = backfill(path, "memories", apply=True, batch_size=1, before_write=race)
    assert result["written"] == result["concurrent_skipped"] == 1
    with sqlite3.connect(path) as conn:
        content, body = conn.execute("SELECT content, content_parts_json FROM memories WHERE id=1").fetchone()
        assert content == raw
        for q in ["标准名", "别名", "12345", "旧名"]:
            assert matches({"content": raw}, q, snapshot) == matches({"content": raw, "content_parts_json": body}, q, snapshot)
        assert references(decode(content, body)) == {"12345"}
    assert backfill(path, "memories", apply=True)["existing"] == 1
    assert backfill(path, "memories", apply=True)["existing"] == 2
    with sqlite3.connect(sorted(tmp_path.glob("*.bak"))[0]) as backup:
        assert backup.execute("SELECT content FROM memories WHERE id=2").fetchone()[0] == raw


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


def test_backfill_repairs_only_missing_index_and_failure_exit(tmp_path):
    script = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/backfill_record_identities.py"))
    path = tmp_path / "quotes.db"
    store = GroupQuoteStore(path)
    ident = store.add("10001", "23456", "名字", "", "99999", content_parts=legacy("[CQ:at,qq=12345]"))
    with store._db:
        encoded = store._db.execute("SELECT content_parts_json FROM quotes WHERE id=?", (ident,)).fetchone()[0]
        store._db.execute("DELETE FROM quotes_member_refs")
    store.close()
    result = script["backfill"](path, "quotes", apply=True)
    assert result["index_repaired"] == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT content_parts_json FROM quotes WHERE id=?", (ident,)).fetchone()[0] == encoded
        assert conn.execute("SELECT qq FROM quotes_member_refs").fetchone()[0] == "12345"
        conn.execute("UPDATE quotes SET content_parts_json='invalid'")
    assert script["main"](["--database", "quotes", "--path", str(path), "--preview-limit", "0"]) == 1


async def test_auto_memory_projection_preserves_history_and_model_strings(llm_service, snapshot, monkeypatch):
    monkeypatch.setattr(llm_service._identity_repository, "snapshot", lambda scope: snapshot)
    scope = "10001"
    historical = "[CQ:at,name=旧称呼,qq=23456] 的历史提及"
    literal = "代码示例 [CQ:at,qq=23456] 保持原文"
    llm_service.store.append_conversation_message(scope, "12345", "user", historical, raw_content=historical, canonical_name="旧标准", sender_name="旧卡")
    llm_service.store.append_conversation_message(scope, "12345", "user", literal, raw_content=literal, canonical_name="旧标准", sender_name="旧卡")
    before = llm_service.store.list_recent_conversation_messages(scope, 10)
    prompts = []
    async def judge(prompt, **kwargs):
        prompts.append(prompt)
        return '{"memories": ["模型写出的小明喜欢编程"]}'
    monkeypatch.setattr(llm_service, "quick_judge", judge)
    llm_service._auto_memory_turns[scope] = 9
    await llm_service._extract_auto_memory(scope_key=scope, user_id="12345", sender_name="旧卡", canonical_name="旧标准", user_text=literal, assistant_text="收到，我会根据当前发言和近期语境判断是否值得记住这些信息。")
    assert "标准名（QQ 12345）" in prompts[0]
    assert "@未登记名片 的历史提及" in prompts[0]
    assert literal in prompts[0]
    record = llm_service.store.list_memories(scope)[0]
    assert record["user_id"] == "12345" and record["scope"] == "user"
    assert record["content"] == "模型写出的小明喜欢编程"
    assert not references(record["content_parts"])
    assert llm_service.store.list_recent_conversation_messages(scope, 10) == before
