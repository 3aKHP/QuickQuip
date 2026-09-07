from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from quickquip.app.web import auth
from quickquip.app.web.action_queue import WebAdminActionQueue
from quickquip.app.web.routes import conversations, llm_runtime
from quickquip.adapters.nonebot import web_admin_actions
from quickquip.llm.agent_records import TriggerKind, TurnOutputStatus, TextPolicy, TurnResponseRecord
from quickquip.llm.store import LLMStore
from quickquip.llm.store_parts.agent_records import UserTriggerPayload


@pytest.fixture
def setup(tmp_path, monkeypatch):
    queue = WebAdminActionQueue(tmp_path / "actions.db")
    store = LLMStore(tmp_path / "llm.db")
    monkeypatch.setattr("quickquip.app.web.action_queue.action_queue", queue)
    monkeypatch.setattr(llm_runtime, "action_queue", queue)
    monkeypatch.setattr(conversations, "_DB", tmp_path / "llm.db")
    monkeypatch.setattr(web_admin_actions, "_ensure_llm_bindings", lambda: None)
    monkeypatch.setattr(web_admin_actions, "get_llm_service", lambda: SimpleNamespace(store=store))
    return queue, store


def _seed(store):
    generation, _ = store.agent_scope_state("12345")
    handle = store.begin_loop(
        "12345", generation, TriggerKind.GROUP_DIRECT,
        UserTriggerPayload(user_id="23456", sender_name="Test", canonical_name="", content="question", raw_content="question"),
    )
    store.commit_turn(handle, TurnResponseRecord(
        text="answer", text_policy=TextPolicy.ALLOWED, output_status=TurnOutputStatus.VISIBLE,
        finish_reason="stop", parts=(),
    ), [], [])
    store.close_loop(handle, "completed", None)
    return store.list_conversation_messages_since("12345", 0, limit=50)


@pytest.mark.parametrize("role, remaining", [("user", 0), ("assistant", 1)])
async def test_deletion_waits_for_worker_and_preserves_domain_scope(setup, role, remaining):
    queue, store = setup
    rows = _seed(store)
    row_id = next(row["id"] for row in rows if row["role"] == role)
    result = conversations.delete_message("12345", row_id)
    assert result["status"] == "queued"
    assert len(store.list_conversation_messages_since("12345", 0, limit=50)) == 2
    action = queue.claim()[0]
    outcome = await web_admin_actions.execute_web_admin_action(action)
    queue.complete(action.id, outcome)
    assert llm_runtime.get_action(action.id)["action"]["result"] == {"deleted": True}
    assert len(store.list_conversation_messages_since("12345", 0, limit=50)) == remaining


async def test_missing_row_reports_deleted_false(setup):
    queue, _ = setup
    result = conversations.delete_message("12345", 999)
    action = queue.claim()[0]
    outcome = await web_admin_actions.execute_web_admin_action(action)
    queue.complete(action.id, outcome)
    assert llm_runtime.get_action(result["action_id"])["action"]["result"] == {"deleted": False}


def test_action_route_is_authenticated_and_read_only(setup):
    queue, _ = setup
    action_id = queue.enqueue("delete_conversation_row", {"row_id": 1})["id"]
    app = FastAPI()
    app.include_router(llm_runtime.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    client = TestClient(app)
    response = client.get(f"/ops/api/llm-runtime/actions/{action_id}")
    assert response.status_code in (401, 503)
    for dependency in auth.protected_dependencies:
        app.dependency_overrides[dependency.dependency] = lambda: None
    assert client.get(f"/ops/api/llm-runtime/actions/{action_id}").json()["action"]["status"] == "queued"
    assert client.get("/ops/api/llm-runtime/actions/missing").status_code == 404
    assert queue.get(action_id)["status"] == "queued"
    queue.fail(action_id, "worker failed")
    assert client.get(f"/ops/api/llm-runtime/actions/{action_id}").json()["action"]["error"] == "worker failed"
