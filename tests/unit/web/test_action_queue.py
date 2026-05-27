from __future__ import annotations

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
