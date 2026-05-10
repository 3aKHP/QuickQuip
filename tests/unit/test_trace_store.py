from quickquip.llm import provider


def test_trace_store_persists_and_clears(monkeypatch, tmp_path):
    path = tmp_path / "quickquip_trace.jsonl"
    monkeypatch.setattr(provider, "_TRACE_STORE_PATH", path)
    provider._TRACE_LOG_LINES.clear()

    provider._record_trace("request", "demo", False, '{"a": 1}')
    provider._record_trace("response", "demo", False, '{"ok": true}')

    assert path.exists()
    assert len(provider.get_trace_entries(0)) == 2
    assert provider.get_trace_entries(1)[0]["direction"] == "response"

    cleared = provider.clear_trace_entries()
    assert cleared == 2
    assert provider.get_trace_entries(0) == []
    assert path.read_text(encoding="utf-8") == ""
