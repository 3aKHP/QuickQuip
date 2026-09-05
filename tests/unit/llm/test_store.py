"""LLMStore 单元测试基线。

覆盖 conversation / memory / session_archive / group_settings 四个域的核心路径。
本测试基线在 store.py mixin 拆分前建立，拆分后必须继续全绿（回归保障）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quickquip.llm.store import LLMStore


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> LLMStore:
    return LLMStore(tmp_path / "test_store.db")


# ── conversation 域 ───────────────────────────────────────────────────────────


def test_conversation_append_and_list_recent(store: LLMStore) -> None:
    store.append_conversation_message(
        1001,
        "user_a",
        "user",
        "你好",
        sender_name="Alice",
        canonical_name="阿桃",
        raw_content="你好呀",
    )
    store.append_conversation_message(1001, None, "assistant", "你好呀")

    rows = store.list_recent_conversation_messages(1001, 10)
    assert len(rows) == 2
    # list_recent 按 id DESC 查再 reverse，返回时间正序
    assert rows[0]["role"] == "user"
    assert rows[0]["content"] == "你好"
    assert rows[0]["sender_name"] == "Alice"
    assert rows[0]["canonical_name"] == "阿桃"
    assert rows[0]["raw_content"] == "你好呀"
    assert rows[1]["role"] == "assistant"
    # user_id 为 None 时返回空字符串
    assert rows[1]["user_id"] == ""


def test_conversation_crop_keeps_last_n_when_no_floor(store: LLMStore) -> None:
    for i in range(5):
        store.append_conversation_message(1002, "u", "user", f"msg{i}")
    store.crop_conversation_messages(1002, floor_id=None, keep_last=2)
    rows = store.list_recent_conversation_messages(1002, 100)
    assert len(rows) == 2
    assert rows[0]["content"] == "msg3"
    assert rows[1]["content"] == "msg4"


def test_conversation_crop_deletes_below_floor(store: LLMStore) -> None:
    for i in range(5):
        store.append_conversation_message(1002, "u", "user", f"msg{i}")
    floor = store.find_anchor_row_id_by_rows(1002, 3)
    assert floor is not None
    # floor = 第 3 新的行（msg2）；keep_last 足够大不起作用
    store.crop_conversation_messages(1002, floor_id=floor, keep_last=100)
    rows = store.list_recent_conversation_messages(1002, 100)
    assert [r["content"] for r in rows] == ["msg2", "msg3", "msg4"]


def test_conversation_list_since_returns_asc_with_ids(store: LLMStore) -> None:
    store.append_conversation_message(1007, "u", "user", "q1", message_id="m1", raw_content="q1 raw")
    store.append_conversation_message(1007, None, "assistant", "a1")
    store.append_conversation_message(1007, "u", "user", "q2", message_id="m2")
    all_rows = store.list_conversation_messages_since(1007, 0, limit=100)
    assert [r["content"] for r in all_rows] == ["q1", "a1", "q2"]
    assert all_rows[0]["id"] > 0
    assert all_rows[0]["message_id"] == "m1"
    assert all_rows[2]["message_id"] == "m2"
    assert all_rows[1]["message_id"] == ""  # None 归一化为空串
    # 锚点含端点：id >= anchor
    since = store.list_conversation_messages_since(1007, all_rows[1]["id"], limit=100)
    assert [r["content"] for r in since] == ["a1", "q2"]
    # limit 兜底（ASC 从锚点侧取，仅用于探测/锚定路径，主读路径不做 LIMIT 截断）
    capped = store.list_conversation_messages_since(1007, 0, limit=2)
    assert [r["content"] for r in capped] == ["q1", "a1"]


def test_find_anchor_row_id_by_rows(store: LLMStore) -> None:
    assert store.find_anchor_row_id_by_rows(1008, 2) is None  # 空表
    for i in range(5):
        store.append_conversation_message(1008, "u", "user", f"msg{i}")
    anchor = store.find_anchor_row_id_by_rows(1008, 2)
    assert anchor is not None
    rows = store.list_conversation_messages_since(1008, anchor, limit=100)
    assert [r["content"] for r in rows] == ["msg3", "msg4"]  # 保留最新 2 行
    assert store.find_anchor_row_id_by_rows(1008, 10) is None  # 总行数不足
    assert store.find_anchor_row_id_by_rows(1008, 0) is None  # 非法入参


def test_find_next_user_row_id(store: LLMStore) -> None:
    store.append_conversation_message(1009, "u", "user", "q1")
    store.append_conversation_message(1009, None, "assistant", "a1")
    store.append_conversation_message(1009, "u", "user", "q2")
    rows = store.list_conversation_messages_since(1009, 0, limit=100)
    first_user, assistant, second_user = rows[0]["id"], rows[1]["id"], rows[2]["id"]
    assert store.find_next_user_row_id(1009, first_user) == first_user
    assert store.find_next_user_row_id(1009, assistant) == second_user
    assert store.find_next_user_row_id(1009, second_user + 1) is None


def test_conversation_count(store: LLMStore) -> None:
    assert store.count_conversation_messages(1003) == 0
    store.append_conversation_message(1003, "u", "user", "a")
    store.append_conversation_message(1003, "u", "assistant", "b")
    assert store.count_conversation_messages(1003) == 2


def test_conversation_clear_returns_deleted(store: LLMStore) -> None:
    store.append_conversation_message(1004, "u", "user", "a")
    store.append_conversation_message(1004, "u", "user", "b")
    deleted = store.clear_conversation_messages(1004)
    assert deleted == 2
    assert store.count_conversation_messages(1004) == 0


def test_conversation_delete_by_message_id_and_update_last_assistant(store: LLMStore) -> None:
    store.append_conversation_message(1005, "u", "user", "q")
    store.append_conversation_message(1005, "u", "assistant", "a")
    # 给最后一条 assistant 消息补上 message_id
    store.update_last_assistant_message_id(1005, "msg-xyz")
    # 按 message_id 删除
    deleted = store.delete_conversation_message_by_message_id(1005, "msg-xyz")
    assert deleted == 1
    rows = store.list_recent_conversation_messages(1005, 100)
    assert len(rows) == 1
    assert rows[0]["role"] == "user"


def test_conversation_get_earliest_message_time(store: LLMStore) -> None:
    assert store.get_earliest_message_time("1006") == ""
    store.append_conversation_message(1006, "u", "user", "first")
    store.append_conversation_message(1006, "u", "user", "second")
    earliest = store.get_earliest_message_time("1006")
    assert earliest != ""
    # earliest 应该是第一条消息的时间（ISO 格式字符串，按字典序比较即可）
    assert earliest.startswith("20")


# ── memory 域 ─────────────────────────────────────────────────────────────────


def test_memory_add_returns_id_and_list_sorts(store: LLMStore) -> None:
    id1 = store.add_memory(2001, "第一条记忆", tags=["tag1"])
    id2 = store.add_memory(2001, "第二条记忆")
    assert isinstance(id1, int) and isinstance(id2, int)
    assert id2 > id1

    rows = store.list_memories(2001, limit=10)
    assert len(rows) == 2
    # list 默认 ORDER BY id DESC
    assert rows[0]["content"] == "第二条记忆"
    assert rows[1]["tags"] == ["tag1"]


def test_memory_list_with_keyword_filter(store: LLMStore) -> None:
    store.add_memory(2002, "苹果很好吃")
    store.add_memory(2002, "香蕉也不错")
    rows = store.list_memories(2002, keyword="苹果")
    assert len(rows) == 1
    assert rows[0]["content"] == "苹果很好吃"


def test_memory_search_chinese_tokenization(store: LLMStore) -> None:
    store.add_memory(2003, "阿桃喜欢画画", user_id="u1", scope="user", confidence=0.9)
    store.add_memory(2003, "小明喜欢唱歌", user_id="u2", scope="user", confidence=0.5)
    # 搜索"阿桃"应命中第一条
    matched = store.search_memories(2003, user_id="u1", query="阿桃", limit=5)
    assert len(matched) == 1
    assert matched[0]["content"] == "阿桃喜欢画画"


def test_memory_delete_and_count(store: LLMStore) -> None:
    store.add_memory(2004, "待删除-苹果")
    store.add_memory(2004, "保留-香蕉")
    deleted = store.delete_memories(2004, "苹果")
    assert deleted == 1
    assert store.count_memories(2004) == 1


def test_memory_prune_and_clear(store: LLMStore) -> None:
    for i in range(5):
        store.add_memory(2005, f"记忆{i}")
    store.prune_memories(2005, keep_last=2)
    assert store.count_memories(2005) == 2
    deleted = store.clear_memories(2005)
    assert deleted == 2
    assert store.count_memories(2005) == 0


# ── session_archive 域 ────────────────────────────────────────────────────────


def test_archive_get_next_number_increments(store: LLMStore) -> None:
    assert store.get_next_archive_number("user_x") == 1
    store.create_session_archive("user_x", 1)
    assert store.get_next_archive_number("user_x") == 2


def test_archive_create_and_get_roundtrip(store: LLMStore) -> None:
    archive_id = store.create_session_archive(
        "user_y", 1, persona_id="persona_a", preset="p", message_count=5
    )
    assert isinstance(archive_id, int)
    archive = store.get_session_archive("user_y", 1)
    assert archive is not None
    assert archive["persona_id"] == "persona_a"
    assert archive["message_count"] == 5


def test_archive_moves_conversation_messages(store: LLMStore) -> None:
    user_id = "user_z"
    private_key = f"private:{user_id}"
    # 在 private scope 下放两条消息
    store.append_conversation_message(private_key, user_id, "user", "私聊消息1")
    store.append_conversation_message(private_key, user_id, "assistant", "回复")

    # 归档：private 消息移到 archive key
    moved = store.archive_conversation_messages(user_id, 1)
    assert moved == 2
    # private scope 应该空了
    assert store.list_recent_conversation_messages(private_key, 100) == []


def test_archive_restore_moves_back(store: LLMStore) -> None:
    user_id = "user_w"
    private_key = f"private:{user_id}"
    store.append_conversation_message(private_key, user_id, "user", "待恢复")
    store.archive_conversation_messages(user_id, 1)

    # 恢复
    restored = store.restore_conversation_messages(user_id, 1)
    assert restored == 1
    rows = store.list_recent_conversation_messages(private_key, 100)
    assert len(rows) == 1
    assert rows[0]["content"] == "待恢复"


def test_archive_list_latest_and_delete_cascade(store: LLMStore) -> None:
    store.create_session_archive("user_v", 1)
    store.create_session_archive("user_v", 2)
    assert store.get_latest_archive_number("user_v") == 2

    archives = store.list_session_archives("user_v")
    assert len(archives) == 2
    # list 按 archive_number DESC
    assert archives[0]["archive_number"] == 2

    # delete 应级联清理对应的 conversation_messages
    user_id = "user_v"
    archive_key = f"archive:{user_id}:1"
    store.append_conversation_message(archive_key, user_id, "user", "归档消息")
    deleted = store.delete_session_archive(user_id, 1)
    assert deleted is True
    assert store.get_session_archive(user_id, 1) is None
    assert store.list_recent_conversation_messages(archive_key, 100) == []


# ── group_settings 域 ─────────────────────────────────────────────────────────


def test_group_settings_get_missing_returns_empty(store: LLMStore) -> None:
    from quickquip.llm.store import GroupSettingsOverride

    override = store.get_group_settings(9999)
    assert isinstance(override, GroupSettingsOverride)
    assert override.enabled is None
    assert override.provider_id is None


def test_group_settings_update_and_readback(store: LLMStore) -> None:
    store.update_group_settings(3001, enabled=True, provider_id="openai", model="gpt-4")
    override = store.get_group_settings(3001)
    assert override.enabled is True
    assert override.provider_id == "openai"
    assert override.model == "gpt-4"

    # 再次 update 部分字段
    store.update_group_settings(3001, model="gpt-4o")
    override = store.get_group_settings(3001)
    assert override.model == "gpt-4o"
    # 之前设的 enabled 应保留
    assert override.enabled is True


def test_group_settings_bool_conversion(store: LLMStore) -> None:
    store.update_group_settings(3002, enabled=False, memory_enabled=True, allow_at=False)
    override = store.get_group_settings(3002)
    assert override.enabled is False
    assert override.memory_enabled is True
    assert override.allow_at is False


# ── _unavailable 守卫路径 ─────────────────────────────────────────────────────


@pytest.fixture
def unavailable_store(tmp_path: Path) -> LLMStore:
    """模拟数据库不可用的 store（_unavailable=True）。"""
    s = LLMStore(tmp_path / "ok.db")
    s._unavailable = True
    return s


def test_unavailable_conversation_raises(unavailable_store: LLMStore) -> None:
    with pytest.raises(RuntimeError, match="数据库不可用"):
        unavailable_store.append_conversation_message(1, "u", "user", "x")
    with pytest.raises(RuntimeError, match="数据库不可用"):
        unavailable_store.list_recent_conversation_messages(1, 10)


def test_unavailable_memory_raises(unavailable_store: LLMStore) -> None:
    with pytest.raises(RuntimeError, match="数据库不可用"):
        unavailable_store.add_memory(1, "x")
    with pytest.raises(RuntimeError, match="数据库不可用"):
        unavailable_store.search_memories(1, user_id=None, query="x", limit=5)


def test_unavailable_session_archive_raises(unavailable_store: LLMStore) -> None:
    with pytest.raises(RuntimeError, match="数据库不可用"):
        unavailable_store.create_session_archive("u", 1)
    with pytest.raises(RuntimeError, match="数据库不可用"):
        unavailable_store.archive_conversation_messages("u", 1)


def test_unavailable_group_settings_raises(unavailable_store: LLMStore) -> None:
    with pytest.raises(RuntimeError, match="数据库不可用"):
        unavailable_store.get_group_settings(1)
    with pytest.raises(RuntimeError, match="数据库不可用"):
        unavailable_store.update_group_settings(1, enabled=True)
