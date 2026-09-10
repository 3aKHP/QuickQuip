from __future__ import annotations

from datetime import datetime, timedelta, timezone

from quickquip.app.web.action_queue import WebAdminActionQueue


def test_action_queue_claim_complete_and_fail(tmp_path):
    queue = WebAdminActionQueue(tmp_path / "actions.db")

    first = queue.enqueue("llm_reload")
    second = queue.enqueue("clear_context", {"scope_key": "12345"})

    claimed = queue.claim(limit=1)
    assert [item.id for item in claimed] == [first["id"]]
    assert claimed[0].status == "running"

    queue.complete(claimed[0].id, {"ok": True})
    queue.fail(second["id"], "boom")

    recent = {item["id"]: item for item in queue.list_recent()}
    assert recent[first["id"]]["status"] == "succeeded"
    assert recent[first["id"]]["result"] == {"ok": True}
    assert recent[second["id"]]["status"] == "failed"
    assert recent[second["id"]]["error"] == "boom"


def test_action_queue_reaps_stale_running_actions(tmp_path):
    queue = WebAdminActionQueue(tmp_path / "actions.db")
    first = queue.enqueue("llm_reload")
    queue.claim(limit=1)

    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with queue._connect() as conn:
        conn.execute(
            "UPDATE web_admin_actions SET updated_at = ? WHERE id = ?",
            (old, first["id"]),
        )

    assert queue.reap_stale_running(timeout_seconds=60) == 1
    recent = {item["id"]: item for item in queue.list_recent()}
    assert recent[first["id"]]["status"] == "failed"
    assert "timed out" in recent[first["id"]]["error"]


def test_get_tracks_one_action_outside_recent_window(tmp_path):
    queue = WebAdminActionQueue(tmp_path / "actions.db")
    action_id = queue.enqueue("delete_conversation_row", {"row_id": 1})["id"]
    assert queue.get(action_id)["status"] == "queued"
    queue.claim(1)
    assert queue.get(action_id)["status"] == "running"
    queue.complete(action_id, {"deleted": True})
    for _ in range(105):
        queue.enqueue("llm_reload")
    assert action_id not in {action["id"] for action in queue.list_recent(100)}
    assert queue.get(action_id)["result"] == {"deleted": True}
    queue.fail(action_id, "failed")
    assert queue.get(action_id)["status"] == "failed"
    assert queue.get("missing") is None
    assert queue.get("' OR 1=1 --") is None


def test_clear_finished_keeps_queued_and_running(tmp_path):
    queue = WebAdminActionQueue(tmp_path / "actions.db")
    done = queue.enqueue("llm_reload")
    failed = queue.enqueue("mcp_reload")
    queue.complete(done["id"], {"ok": True})
    queue.fail(failed["id"], "boom")

    running = queue.enqueue("health_check")
    queue.claim(limit=1)
    queued = queue.enqueue("rules_reload")

    assert queue.clear_finished() == 2
    remaining = {item["id"]: item for item in queue.list_recent()}
    assert set(remaining) == {running["id"], queued["id"]}
    assert remaining[running["id"]]["status"] == "running"
    assert remaining[queued["id"]]["status"] == "queued"
    assert queue.clear_finished() == 0
