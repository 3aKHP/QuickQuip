from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

import pytest

from quickquip.app.identities import IdentityRepository, IdentitySnapshot
from quickquip.common.identity import IdentityEntry
from quickquip.common.record_content import (
    from_segments,
    legacy,
    plain,
    references,
    render,
    validate,
)
from quickquip.common.record_storage import migrate


from tests.fixtures.record_identities import snapshot as snapshot
from tests.fixtures.record_identities import index, write_identity

def test_protocol_boundaries(snapshot):
    raw = "[CQ:at,name=旧&#44;名&amp;,extra=1,qq=12345] 喜欢 [CQ:image,file=x] @QQ23456"
    body = legacy(raw)
    assert references(body) == {"12345", "23456"}
    assert render(body, snapshot) == "@标准名 喜欢 [图片] @未登记名片"
    assert body["parts"][1]["name"] == "旧,名&"
    assert render(
        legacy("12345 @名字 abc@QQ12345 @QQ12345abc [CQ:at,qq=no]"), snapshot
    ) == "12345 @名字 abc@QQ12345 @QQ12345abc [CQ:at,qq=no]"
    literal = from_segments([{"type": "text", "data": {"text": raw}}])
    assert render(literal, snapshot) == raw
    assert references(literal) == set()


def test_command_only_stripped_from_text_segment(snapshot):
    message = [
        {"type": "text", "data": {"text": "/remember "}},
        {"type": "at", "data": {"qq": "12345", "name": "旧名"}},
        {"type": "text", "data": {"text": " /remember 保留"}},
        {"type": "at", "data": {"qq": "all"}},
        {"type": "at", "data": {"qq": "99999", "name": "机器人"}},
    ]
    assert (
        render(from_segments(message, "remember"), snapshot)
        == "@标准名 /remember 保留@全体成员@机器人"
    )
    assert render(from_segments(message), snapshot).startswith("/remember ")


@pytest.mark.parametrize(
    "part",
    [
        {"type": "member", "qq": "all"},
        {"type": "member", "qq": 12345},
        {"type": "member", "qq": "12345", "usage": "bad"},
        {"type": "member", "qq": "12345", "name": []},
        {"type": "member", "qq": "12345", "usage": []},
        {"type": "media", "media": []},
        {"type": "media", "media": "bad"},
        {"type": "text", "text": None},
    ],
)
def test_validation_rejects_invalid_parts(part):
    with pytest.raises(ValueError):
        validate({"version": 1, "parts": [part]})


def test_validation_enforces_length():
    with pytest.raises(ValueError):
        validate(plain("x" * 4097))


def test_identity_merge_and_ambiguous_names():
    global_index = index(
        IdentityEntry("同名", ["12345"], [], ""), IdentityEntry("同名", ["23456"], [], "")
    )
    group = index(IdentityEntry("群标准名", ["12345"], ["旧别名"], ""))
    snap = IdentitySnapshot(global_index.merge(group))
    assert snap.name("12345") == "群标准名"
    assert snap.name("23456") == "同名"
    assert len(global_index.search("同名")) == 2
    assert IdentitySnapshot(global_index).candidates("同名") == {"12345", "23456"}


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
        assert len(
            [r for r in conn.execute("PRAGMA table_info(memories)") if r[1] == "content_parts_json"]
        ) == 1



def test_record_query_resolves_candidates_once(snapshot, monkeypatch):
    from quickquip.common.record_search import RecordQuery
    calls = []
    original = snapshot.candidates
    def counted(query):
        calls.append(query)
        return original(query)
    monkeypatch.setattr(snapshot, "candidates", counted)
    query = RecordQuery("别名", snapshot)
    for _ in range(300):
        assert query.matches({"content": "[CQ:at,qq=12345]"})
        assert not query.matches({"content": "无关内容"})
    assert calls == ["别名"]


def test_group_index_cache_reuses_merge_until_reload(tmp_path):
    path = tmp_path / "identities.yaml"
    write_identity(path, "全局")
    write_identity(tmp_path / "10001" / "identities.yaml", "本群")
    repo = IdentityRepository(path, tmp_path / "stats.json")
    before = repo.snapshot("10001").index
    assert repo.snapshot("10001").index is before
    write_identity(tmp_path / "10001" / "identities.yaml", "更新")
    repo.invalidate()
    after = repo.snapshot("10001").index
    assert after is not before
    assert after.resolve_user("12345").canonical_name == "更新"


def test_record_storage_rejects_unknown_table(tmp_path):
    from quickquip.common.record_storage import save_parts
    with sqlite3.connect(tmp_path / "db") as conn, pytest.raises(
        ValueError, match="unsupported record table"
    ):
        save_parts(conn, "not_a_record", 1, "10001", plain("text"))
