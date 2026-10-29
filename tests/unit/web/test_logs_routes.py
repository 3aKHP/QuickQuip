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


@pytest.fixture
def media_client(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from quickquip.app.web import app as web_app, auth
    from quickquip.llm.provider.trace import LLMTraceStore

    store = LLMTraceStore(tmp_path / "trace.db", media_min_bytes=64)
    monkeypatch.setattr(logs, "trace_store", store)
    app = FastAPI()
    web_app._register_security_headers(app)
    app.include_router(logs.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    with TestClient(app) as client:
        yield client, app, store


@pytest.mark.parametrize("mime", ["text/html", "image/svg+xml", "image/png"])
def test_media_download_requires_auth_and_forces_attachment(media_client, mime):
    import base64
    import json
    from quickquip.app.web import auth

    client, app, store = media_client
    raw = b"synthetic untrusted content " * 8
    payload = f"data:{mime};base64," + base64.b64encode(raw).decode()
    text = json.dumps({"image": payload})
    call_id = store.begin_call(
        provider_id="demo", protocol="openai", model="test", stream=False,
        method="POST", url="https://example.test", request_headers="{}",
        request_text=text, request_bytes=len(text.encode()),
    )
    sha = store.get_call(call_id)["media_truncation"]["request"]["splices"][0]["sha256"]
    path = f"/ops/api/logs/trace/blobs/{sha}"
    assert client.get(path).status_code == 401
    assert client.get(f"/ops/api/logs/trace/calls/{call_id}?restore=true").status_code == 401
    app.dependency_overrides[auth.require_admin_session] = lambda: {"role": "admin"}
    response = client.get(path)
    assert response.status_code == 200
    assert response.content == raw
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"] == f'attachment; filename="{sha}.bin"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert client.get("/ops/api/logs/trace/blobs/invalid").status_code == 422
    assert client.get("/ops/api/logs/trace/blobs/" + "0" * 64).status_code == 404

    assert client.get(f"/ops/api/logs/trace/calls/{call_id}").json()["request_text"] != text
    assert client.get(f"/ops/api/logs/trace/calls/{call_id}?restore=false").json()[
        "request_text"
    ] != text
    assert client.get(f"/ops/api/logs/trace/calls/{call_id}?restore=true").json()[
        "request_text"
    ] == text
    assert client.get("/ops/api/logs/trace/calls/missing?restore=true").status_code == 404
    blob = store.blob_store.path_for(sha)
    blob.write_text("corrupt", encoding="utf-8")
    assert client.get(f"/ops/api/logs/trace/calls/{call_id}?restore=true").status_code == 409
    blob.unlink()
    assert client.get(f"/ops/api/logs/trace/calls/{call_id}?restore=true").status_code == 409


@pytest.mark.parametrize("corruption", ["json", "field", "hashes", "offset", "unwrapped"])
def test_restore_rejects_corrupt_manifest_with_409(media_client, corruption):
    import json
    from quickquip.app.web import auth

    client, app, store = media_client
    app.dependency_overrides[auth.require_admin_session] = lambda: {"role": "admin"}
    text = json.dumps({"image": "A" * 256})
    call_id = store.begin_call(
        provider_id="demo", protocol="openai", model="test", stream=False,
        method="POST", url="https://example.test", request_headers="{}",
        request_text=text, request_bytes=len(text.encode()),
    )
    manifest = store.get_call(call_id)["media_truncation"]
    if corruption == "unwrapped":
        manifest = manifest["request"]
    elif corruption == "field":
        manifest["request"] = []
    elif corruption == "hashes":
        manifest["request"].pop("full_sha256")
        manifest["request"].pop("truncated_sha256")
    elif corruption == "offset":
        manifest["request"]["splices"][0]["offset"] = None
    serialized = "{broken" if corruption == "json" else json.dumps(manifest)
    with store._connect() as conn:
        conn.execute(
            "UPDATE llm_http_traces SET media_truncation=? WHERE call_id=?", (serialized, call_id),
        )
    assert client.get(f"/ops/api/logs/trace/calls/{call_id}?restore=true").status_code == 409
