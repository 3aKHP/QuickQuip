import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from quickquip.app.identities import IdentityRepository
from quickquip.app.web.routes import memory
from quickquip.common.record_content import legacy
from quickquip.llm.store import LLMStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "_DB", tmp_path / "llm.db")
    path = tmp_path / "identities.yaml"
    path.write_text(
        'people:\n  - canonical_name: "标准名"\n    qq_ids: ["12345"]\n    aliases: ["别名"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(memory, "web_identities", IdentityRepository(path, tmp_path / "stats.json"))
    monkeypatch.setattr(memory.audit_logger, "log", lambda *args, **kwargs: None)
    app = FastAPI()
    app.include_router(memory.router, prefix="/api")
    with TestClient(app) as client:
        yield client


def test_reference_edit_metadata_and_plain_client(client):
    body = legacy("[CQ:at,qq=12345,name=旧名] 的事实")
    result = client.post("/api/memory/10001", json={"content_parts": body})
    assert result.status_code == 201
    ident = result.json()["id"]
    row = client.get("/api/memory/10001?keyword=别名").json()[0]
    assert row["content_display"] == "@标准名 的事实"
    assert row["content"] == "@旧名 的事实"
    result = client.put(f"/api/memory/10001/{ident}", json={"tags": ["分类"], "confidence": 0.3})
    assert result.status_code == 200
    store = LLMStore(memory._DB)
    with store._connect() as conn:
        before = conn.execute(
            "SELECT content_parts_json FROM memories WHERE id=?", (ident,)
        ).fetchone()[0]
        assert json.loads(before) == body
        assert conn.execute(
            "SELECT qq FROM memories_member_refs WHERE record_id=?", (ident,)
        ).fetchone()[0] == "12345"
    # Old clients submit text; even a literal CQ example must stay text.
    text = "代码 [CQ:at,qq=12345]"
    assert client.put(f"/api/memory/10001/{ident}", json={"content": text}).status_code == 200
    row = client.get("/api/memory/10001").json()[0]
    assert row["content_display"] == text
    with store._connect() as conn:
        assert not conn.execute("SELECT * FROM memories_member_refs").fetchall()
    assert client.put(f"/api/memory/10001/{ident}", json={"content_parts": body}).status_code == 200
    assert client.delete(f"/api/memory/10001/{ident}").status_code == 200
    with store._connect() as conn:
        assert not conn.execute("SELECT * FROM memories_member_refs").fetchall()


@pytest.mark.parametrize(
    "body",
    [
        {"version": 2, "parts": []},
        {"version": 1, "parts": [{"type": "member", "qq": "oops"}]},
        {"version": 1, "parts": [{"type": "text", "text": "a" * 4097}]},
    ],
)
def test_invalid_parts_rejected(client, body):
    assert client.post("/api/memory/10001", json={"content_parts": body}).status_code == 422
    assert client.get("/api/memory/10001").json() == []


def test_candidates_from_web_files_and_scope(client, tmp_path):
    path = tmp_path / "10001" / "identities.yaml"
    path.parent.mkdir()
    path.write_text(
        'people:\n  - canonical_name: "群名"\n    qq_ids: ["12345"]\n    aliases: ["群别名"]\n'
    )
    (tmp_path / "stats.json").write_text(json.dumps({"10001": {"user_names": {"23456": "群名片"}}}))
    candidates = client.get("/api/members/10001?query=群").json()
    assert {m["qq"] for m in candidates} == {"12345", "23456"}
    assert client.get("/api/members/10002?query=群").json() == []
    assert client.get("/api/members/10001?query=群别名").json()[0]["name"] == "群名"


def test_members_route_protected():
    from quickquip.app.web.app import create_app
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/ops/api/members/10001").status_code == 401


def test_member_candidates_can_page_past_first_hundred(client, tmp_path):
    members = {str(20000 + i): "同名片" for i in range(105)}
    (tmp_path / "stats.json").write_text(json.dumps({"10001": {"user_names": members}}))
    first = client.get("/api/members/10001?query=同名片&offset=0&limit=100").json()
    second = client.get("/api/members/10001?query=同名片&offset=100&limit=100").json()
    assert len(first) == 100 and len(second) == 5
    assert {member["qq"] for member in first + second} == set(members)
