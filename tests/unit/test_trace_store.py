from quickquip.llm import provider


def test_trace_store_persists_and_clears(monkeypatch, tmp_path):
    today_path = tmp_path / "quickquip_trace_2026-05-21.jsonl"
    monkeypatch.setattr(provider, "_TRACE_DIR", tmp_path)
    monkeypatch.setattr(provider, "_daily_trace_path", lambda: today_path)
    # Disable cleanup so it doesn't try to stat/delete files
    monkeypatch.setattr(provider, "_cleanup_old_traces", lambda: None)
    provider._TRACE_LOG_LINES.clear()

    provider._record_trace("request", "demo", False, '{"a": 1}')
    provider._record_trace("response", "demo", False, '{"ok": true}')

    assert today_path.exists()
    assert "a" in today_path.read_text(encoding="utf-8")
    assert provider.get_trace_entries(0)[0]["payload"] == '{"a": 1}'
    assert len(provider.get_trace_entries(0)) == 2
    assert provider.get_trace_entries(1)[0]["direction"] == "response"

    cleared = provider.clear_trace_entries()
    assert cleared == 2
    assert provider.get_trace_entries(0) == []
