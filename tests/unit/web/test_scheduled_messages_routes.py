from __future__ import annotations

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
