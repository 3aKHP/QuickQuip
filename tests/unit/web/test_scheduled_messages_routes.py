from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
HTTPException = fastapi.HTTPException

from quickquip.app.web.routes import scheduled_messages as sm  # noqa: E402
from quickquip.chat.scheduled_messages import ScheduledMessageStore  # noqa: E402


@pytest.fixture()
def store(monkeypatch, tmp_path: Path) -> ScheduledMessageStore:
    s = ScheduledMessageStore(tmp_path / "scheduled_messages.json")
    monkeypatch.setattr(sm, "_get_store", lambda: s)
    monkeypatch.setattr(sm.audit_logger, "log", lambda *a, **k: None)
    return s


@pytest.fixture()
def enqueued(monkeypatch) -> list[tuple[str, dict]]:
    captured: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        sm.action_queue,
        "enqueue",
        lambda action_type, payload=None: captured.append((action_type, payload)) or {"id": "a1"},
    )
    return captured


def _create_body(**overrides) -> sm.ScheduledMessageCreate:
    data = {"cron": "0 7 * * *", "group_ids": ["10001", "10002"], "message": "早安"}
    data.update(overrides)
    return sm.ScheduledMessageCreate(**data)


def _pinned_cron(dt: datetime) -> str:
    return f"{dt.minute} {dt.hour} {dt.day} {dt.month} *"


def test_crud_flow(store, enqueued):
    created = sm.create_scheduled_message(_create_body(), object())
    assert created["origin"] == "web"
    assert created["enabled"] is True
    assert created["kind"] == "text"
    assert created["recurring"] is True
    assert enqueued == [("scheduler_reload", {})]

    listed = sm.list_scheduled_messages()["jobs"]
    assert [j["id"] for j in listed] == [created["id"]]

    # group_id 过滤
    assert sm.list_scheduled_messages(group_id="10001")["jobs"]
    assert sm.list_scheduled_messages(group_id="99999")["jobs"] == []

    updated = sm.update_scheduled_message(
        created["id"],
        sm.ScheduledMessageUpdate(cron="30 8 * * *", enabled=False),
        object(),
    )
    assert updated["cron"] == "30 8 * * *"
    assert updated["enabled"] is False
    assert updated["message"] == "早安"  # 未提交的字段保持不变

    toggled = sm.update_scheduled_message(
        created["id"], sm.ScheduledMessageUpdate(enabled=True), object()
    )
    assert toggled["enabled"] is True

    assert sm.delete_scheduled_message(created["id"], object()) == {"ok": True}
    assert sm.list_scheduled_messages()["jobs"] == []
    assert [a for a, _ in enqueued] == ["scheduler_reload"] * 4


def test_create_invalid_cron_returns_400(store, enqueued):
    with pytest.raises(HTTPException) as exc:
        sm.create_scheduled_message(_create_body(cron="not a cron"), object())
    assert exc.value.status_code == 400
    assert enqueued == []
    assert store.list() == []


def test_create_invalid_group_id_returns_400(store, enqueued):
    with pytest.raises(HTTPException) as exc:
        sm.create_scheduled_message(_create_body(group_ids=["abc"]), object())
    assert exc.value.status_code == 400
    assert enqueued == []


def test_update_invalid_cron_returns_400(store):
    created = sm.create_scheduled_message(_create_body(), object())
    with pytest.raises(HTTPException) as exc:
        sm.update_scheduled_message(
            created["id"], sm.ScheduledMessageUpdate(cron="61 * * * *"), object()
        )
    assert exc.value.status_code == 400
    assert store.get(created["id"]).cron == "0 7 * * *"


def test_update_not_found_returns_404(store):
    with pytest.raises(HTTPException) as exc:
        sm.update_scheduled_message("sm_missing", sm.ScheduledMessageUpdate(message="x"), object())
    assert exc.value.status_code == 404


def test_delete_not_found_returns_404(store, enqueued):
    with pytest.raises(HTTPException) as exc:
        sm.delete_scheduled_message("sm_missing", object())
    assert exc.value.status_code == 404
    assert enqueued == []


def test_create_with_llm_kind_and_one_shot(store):
    created = sm.create_scheduled_message(
        _create_body(kind="llm", recurring=False, message="总结一下昨天的群聊"),
        object(),
    )
    assert created["kind"] == "llm"
    assert created["recurring"] is False
    job = store.get(created["id"])
    assert job.kind == "llm"
    assert job.recurring is False


def test_create_invalid_kind_returns_400(store, enqueued):
    with pytest.raises(HTTPException) as exc:
        sm.create_scheduled_message(_create_body(kind="image"), object())
    assert exc.value.status_code == 400
    assert enqueued == []
    assert store.list() == []


def test_update_kind_and_recurring(store):
    created = sm.create_scheduled_message(_create_body(), object())
    updated = sm.update_scheduled_message(
        created["id"],
        sm.ScheduledMessageUpdate(kind="llm", recurring=False),
        object(),
    )
    assert updated["kind"] == "llm"
    assert updated["recurring"] is False
    assert updated["message"] == "早安"  # 未提交的字段保持不变


def test_update_invalid_kind_returns_400(store):
    created = sm.create_scheduled_message(_create_body(), object())
    with pytest.raises(HTTPException) as exc:
        sm.update_scheduled_message(
            created["id"], sm.ScheduledMessageUpdate(kind="bad"), object()
        )
    assert exc.value.status_code == 400
    assert store.get(created["id"]).kind == "text"


def test_update_empty_body_is_noop(store, enqueued, monkeypatch):
    """空 PUT 不产生审计条目、不触发 reload、不落盘改动。"""
    created = sm.create_scheduled_message(_create_body(), object())
    before = store.get(created["id"]).to_dict()
    audit_calls: list[dict] = []
    monkeypatch.setattr(
        sm.audit_logger, "log", lambda *a, **k: audit_calls.append(k)
    )

    updated = sm.update_scheduled_message(
        created["id"], sm.ScheduledMessageUpdate(), object()
    )

    assert updated == before
    assert audit_calls == []
    assert enqueued == [("scheduler_reload", {})]  # 只有 create 那一次
    assert store.get(created["id"]).to_dict() == before  # updated_at 未跳动


def test_create_one_off_with_past_date_returns_400(store, enqueued):
    """一次性任务钉在今年已过的日期会被拒绝（否则会静默等到来年）。"""
    pytest.importorskip("apscheduler")
    past = _pinned_cron(datetime.now() - timedelta(days=1))
    with pytest.raises(HTTPException) as exc:
        sm.create_scheduled_message(_create_body(cron=past, recurring=False), object())
    assert exc.value.status_code == 400
    assert enqueued == []
    assert store.list() == []


def test_create_one_off_with_future_date_ok(store):
    future = _pinned_cron(datetime.now() + timedelta(days=1))
    created = sm.create_scheduled_message(
        _create_body(cron=future, recurring=False), object()
    )
    assert created["recurring"] is False
    assert created["cron"] == future


def test_create_recurring_with_past_pinned_date_ok(store):
    """同样的钉死日期，recurring=True（每年重复的周年提醒）不受一次性校验限制。"""
    past = _pinned_cron(datetime.now() - timedelta(days=1))
    created = sm.create_scheduled_message(_create_body(cron=past, recurring=True), object())
    assert created["recurring"] is True


def test_update_to_one_off_with_past_date_returns_400(store, enqueued):
    pytest.importorskip("apscheduler")
    past = _pinned_cron(datetime.now() - timedelta(days=1))
    created = sm.create_scheduled_message(_create_body(), object())
    with pytest.raises(HTTPException) as exc:
        sm.update_scheduled_message(
            created["id"],
            sm.ScheduledMessageUpdate(cron=past, recurring=False),
            object(),
        )
    assert exc.value.status_code == 400
    job = store.get(created["id"])
    assert job.cron == "0 7 * * *"
    assert job.recurring is True
    assert [a for a, _ in enqueued] == ["scheduler_reload"]  # 只有 create 那一次


def test_update_message_only_on_stale_one_off_not_blocked(store):
    """存量一次性任务（如日期已过但已禁用）只改文案时不触发未来时间校验。"""
    past = _pinned_cron(datetime.now() - timedelta(days=1))
    # 直接落盘构造存量任务：store.add 已拒绝创建过期一次性任务，
    # 过期任务只能来自校验上线前的历史数据或外部编辑。
    store.path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "sm_stale",
                        "cron": past,
                        "group_ids": ["10001"],
                        "message": "旧文案",
                        "recurring": False,
                        "origin": "web",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    updated = sm.update_scheduled_message(
        "sm_stale", sm.ScheduledMessageUpdate(message="新文案"), object()
    )
    assert updated["message"] == "新文案"
