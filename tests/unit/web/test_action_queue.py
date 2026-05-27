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
