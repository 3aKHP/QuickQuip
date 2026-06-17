from quickquip.llm.provider import trace


def test_trace_store_persists_and_clears(monkeypatch, tmp_path):
    today_path = tmp_path / "quickquip_trace_2026-05-21.jsonl"
    monkeypatch.setattr(trace, "_TRACE_DIR", tmp_path)
    monkeypatch.setattr(trace, "_daily_trace_path", lambda: today_path)
    # Disable cleanup so it doesn't try to stat/delete files
    monkeypatch.setattr(trace, "_cleanup_old_traces", lambda: None)
    trace._TRACE_LOG_LINES.clear()

    trace._record_trace("request", "demo", False, '{"a": 1}')
    trace._record_trace("response", "demo", False, '{"ok": true}')

    assert today_path.exists()
    assert "a" in today_path.read_text(encoding="utf-8")
    assert trace.get_trace_entries(0)[0]["payload"] == '{"a": 1}'
    assert len(trace.get_trace_entries(0)) == 2
    assert trace.get_trace_entries(1)[0]["direction"] == "response"

    cleared = trace.clear_trace_entries()
    assert cleared == 2
    assert trace.get_trace_entries(0) == []
