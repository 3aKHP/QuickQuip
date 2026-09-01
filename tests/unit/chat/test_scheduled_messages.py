"""ScheduledMessageStore 的持久化边界测试：坏文件容错与跨写者合并。"""

from __future__ import annotations

import json

import pytest

from quickquip.chat.scheduled_messages import ScheduledMessageStore, validate_cron


def test_add_and_list_roundtrip(tmp_path):
    store = ScheduledMessageStore(tmp_path / "sm.json")
    job = store.add(
        cron="0 7 * * *",
        group_ids=[123, "456"],
        message="早上好！",
        kind="llm",
        recurring=False,
        origin="command",
    )
    loaded = store.list()
    assert [j.id for j in loaded] == [job.id]
    assert loaded[0].kind == "llm"
    assert loaded[0].recurring is False
    assert loaded[0].group_ids == ["123", "456"]


def test_bad_json_treated_as_empty(tmp_path):
    path = tmp_path / "sm.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = ScheduledMessageStore(path)
    assert store.list() == []
    # 写入后文件恢复为合法 JSON
    store.add(cron="0 7 * * *", group_ids=[123], message="恢复")
    assert len(store.list()) == 1


def test_invalid_entries_skipped(tmp_path):
    path = tmp_path / "sm.json"
    path.write_text(
        json.dumps(
            {
                "jobs": [
                    {"id": "sm_good", "cron": "0 7 * * *", "group_ids": ["123"], "message": "好"},
                    {"id": "", "cron": "0 7 * * *", "group_ids": ["123"], "message": "无 id"},
                    {"id": "sm_bad", "cron": "not-a-cron", "group_ids": ["123"], "message": "坏 cron"},
                    "not-a-dict",
                ]
            }
        ),
        encoding="utf-8",
    )
    store = ScheduledMessageStore(path)
    assert [j.id for j in store.list()] == ["sm_good"]


def test_cross_writer_updates_not_lost(tmp_path):
    """两个 store 实例（模拟 bot 与 web 双进程）交替写入不丢更新。"""
    path = tmp_path / "sm.json"
    bot_store = ScheduledMessageStore(path)
    web_store = ScheduledMessageStore(path)

    job_a = bot_store.add(cron="0 7 * * *", group_ids=[123], message="来自 bot")
    job_b = web_store.add(cron="0 8 * * *", group_ids=[123], message="来自 web")
    bot_store.set_enabled(job_b.id, False)
    web_store.remove(job_a.id)

    remaining = bot_store.list()
    assert [j.id for j in remaining] == [job_b.id]
    assert remaining[0].enabled is False


def test_validate_cron_rejects_invalid():
    validate_cron("*/5 0-7 * * 0,6")
    with pytest.raises(ValueError, match="5 段"):
        validate_cron("0 7 * *")
    with pytest.raises(ValueError, match="非法 cron"):
        validate_cron("61 7 * * *")
    with pytest.raises(ValueError):
        validate_cron("0 25 * * *")


def test_update_with_no_effective_fields_is_noop(tmp_path):
    """无有效字段的 update 为空操作：不跳 updated_at、不落盘。"""
    store = ScheduledMessageStore(tmp_path / "sm.json")
    job = store.add(cron="0 7 * * *", group_ids=[123], message="早安")
    before = job.to_dict()

    same = store.update(job.id)
    assert same is not None
    assert same.to_dict() == before
    assert store.update(job.id, enabled=None, unknown_field="x").to_dict() == before


def test_update_for_audit_captures_before_after(tmp_path):
    """update_for_audit 在同一锁视图返回 before/after；不存在返回 (None, None)。"""
    store = ScheduledMessageStore(tmp_path / "sm.json")
    job = store.add(cron="0 7 * * *", group_ids=[123], message="早安")

    before, after = store.update_for_audit(job.id, message="晚安")
    assert before is not None and before.message == "早安"
    assert after is not None and after.message == "晚安"
    assert before.id == after.id
    assert after.updated_at >= before.updated_at  # 秒级精度，同秒内允许相等

    noop_before, noop_after = store.update_for_audit(job.id)
    assert noop_after is noop_before or noop_after.to_dict() == noop_before.to_dict()

    assert store.update_for_audit("sm_missing", message="x") == (None, None)
