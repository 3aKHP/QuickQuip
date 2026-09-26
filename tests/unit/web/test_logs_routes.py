from pathlib import Path

import pytest
from fastapi import HTTPException

from quickquip.app.web.routes import logs


def _patch_logs_dir(monkeypatch, tmp_path: Path) -> Path:
    base = tmp_path / "logs"
    base.mkdir()
    monkeypatch.setattr(logs, "_LOGS_DIR", base)
    return base


def test_list_logs_sorts_and_marks_current(monkeypatch, tmp_path):
    base = _patch_logs_dir(monkeypatch, tmp_path)
    (base / "quickquip_2026-05-09.log").write_text("y\n", encoding="utf-8")
    (base / "quickquip_2026-05-10.log").write_text("x\n", encoding="utf-8")
    (base / "ignore.txt").write_text("nope", encoding="utf-8")

    result = logs.list_logs()

    assert result["current_file"] == "quickquip_2026-05-10.log"
    assert [item["name"] for item in result["files"]] == [
        "quickquip_2026-05-10.log", "quickquip_2026-05-09.log"
    ]
    assert result["files"][0]["is_current"] is True


def test_get_log_tail_returns_last_lines(monkeypatch, tmp_path):
    base = _patch_logs_dir(monkeypatch, tmp_path)
    path = base / "quickquip_2026-05-10.log"
    path.write_text("line1\nline2\nline3\n", encoding="utf-8")

    result = logs.get_log_tail("quickquip_2026-05-10.log", lines=2)

    assert result["lines"] == ["line2", "line3"]
    assert result["name"] == "quickquip_2026-05-10.log"


def test_get_log_tail_rejects_invalid_name(monkeypatch, tmp_path):
    _patch_logs_dir(monkeypatch, tmp_path)

    with pytest.raises(HTTPException) as exc:
        logs.get_log_tail("../secret.log")

    assert exc.value.status_code == 422


def test_list_trace_calls_returns_metadata_page(monkeypatch):
    calls = [
        {"id": 9, "call_id": "call-9", "state": "success"},
        {"id": 8, "call_id": "call-8", "state": "pending"},
    ]

    class _Store:
        def list_calls(self, **kwargs):
            assert kwargs == {"limit": 2, "before_id": 10}
            return calls

    monkeypatch.setattr(logs, "trace_store", _Store())

    result = logs.list_trace_calls(limit=2, before_id=10)

    assert result == {"calls": calls, "next_before_id": 8}


def test_get_trace_call_loads_detail_on_demand(monkeypatch):
    detail = {
        "id": 1,
        "call_id": "call-1",
        "request_text": '{"hello":"world"}',
        "response_text": '[{"delta":"ok"}]',
    }

    class _Store:
        def get_call(self, call_id):
            return detail if call_id == "call-1" else None

    monkeypatch.setattr(logs, "trace_store", _Store())

    assert logs.get_trace_call("call-1") is detail
    with pytest.raises(HTTPException) as exc:
        logs.get_trace_call("missing")
    assert exc.value.status_code == 404


def test_trace_sse_contains_metadata_as_one_event():
    encoded = logs._encode_trace_sse(
        {"event_id": 12, "call_id": "call-1", "state": "success"}
    )

    assert encoded.startswith("id: 12\n")
    assert '"call_id":"call-1"' in encoded
    assert encoded.endswith("\n\n")
