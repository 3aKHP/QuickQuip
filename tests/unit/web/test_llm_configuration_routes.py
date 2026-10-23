"""Authenticated configuration HTTP contract and sensitive-data boundaries."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from quickquip.app.web import auth
from quickquip.app.web.routes import llm_configuration as routes
from quickquip.app.web.session_store import WebAdminSessionStore

BASE = "/ops/api/llm-configuration"


@pytest.fixture
def client(monkeypatch, tmp_path, config_service):
    monkeypatch.setattr(auth, "get_web_admin_password", lambda: "test-admin-password")
    sessions = WebAdminSessionStore(tmp_path / "sessions.db")
    monkeypatch.setattr(auth, "_session_store", lambda: sessions)
    monkeypatch.setattr(routes.audit_logger, "log", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(auth.router, prefix="/ops/api")
    app.include_router(routes.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    with TestClient(app, headers={"origin": "http://testserver"}) as result:
        yield result


def login(client):
    assert (
        client.post("/ops/api/auth/login", json={"password": "test-admin-password"}).status_code
        == 200
    )


def provider():
    return {
        "id": "p",
        "protocol": "openai",
        "base_url": "https://example.com/v1",
        "api_key_env": "MODEL_KEY",
        "default_model": "owner/model",
        "models": [{"model": "owner/model", "parameters": {"temperature": 0}}],
    }


def test_authentication_same_origin_and_flat_error(client):
    response = client.get(BASE)
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"
    assert set(response.json()) == {"code", "message", "field_path", "details"}
    login(client)
    response = client.put(BASE, headers={"origin": "https://attacker.example"}, json={})
    assert response.status_code == 403


def test_import_preview_save_apply_and_conflict_flow(client, config_service):
    login(client)
    initial = client.get(BASE).json()
    document = initial["document"]
    document["providers"] = [provider()]
    body = {"document": document, "expected_draft_revision": initial["revision"]}
    preview = client.post(f"{BASE}/import/preview", json=body)
    assert preview.status_code == 200
    assert preview.json()["valid"] and preview.json()["warnings"]
    assert config_service.read()["revision"] == 1
    saved = client.post(f"{BASE}/import", json=body)
    assert saved.status_code == 200
    assert saved.json()["revision"] == 2
    assert config_service.read("published")["revision"] == 1
    conflict = client.put(BASE, json=body)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "revision_conflict"
    operation = client.post(
        f"{BASE}/apply", json={"expected_draft_revision": 2, "request_id": "apply"}
    )
    assert operation.status_code == 202
    assert operation.json()["status"] == "queued"
    assert client.get(f"{BASE}/operations/{operation.json()['id']}").json()["status"] == "queued"
    assert client.get(f"{BASE}/operations").json()["operations"][0]["id"] == operation.json()["id"]
    assert "claim_token" not in operation.json()
    assert config_service.status()["published_revision"] == 1
    assert client.post(f"{BASE}/operations/{operation.json()['id']}/cancel").status_code == 200


def test_errors_and_exports_never_contain_credentials(client, config_service, monkeypatch):
    login(client)
    monkeypatch.setenv("MODEL_KEY", "secret-value-never-export")
    document = config_service.read()["document"]
    document["providers"] = [provider()]
    document["providers"][0]["headers"] = {"Authorization": "Bearer literal-secret-value"}
    invalid = client.put(BASE, json={"expected_draft_revision": 1, "document": document})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "literal_secret"
    assert "literal-secret-value" not in invalid.text
    document["providers"][0]["headers"] = {"Authorization": "Bearer ${MODEL_KEY}"}
    assert (
        client.put(BASE, json={"expected_draft_revision": 1, "document": document}).status_code
        == 200
    )
    export = client.get(f"{BASE}/export")
    assert "${MODEL_KEY}" in export.text
    assert "secret-value-never-export" not in export.text
    invalid_body = client.post(
        f"{BASE}/apply", json={"request_id": "x", "expected_draft_revision": "sensitive-input"}
    )
    assert invalid_body.status_code == 422
    assert "sensitive-input" not in invalid_body.text


def test_body_limit_without_trusted_content_length(client, config_service):
    login(client)
    oversized = json.dumps(
        {"document": {"large": "x" * routes.MAX_BODY_BYTES}, "expected_draft_revision": 1}
    ).encode()
    response = client.put(
        BASE,
        content=iter([oversized[:500000], oversized[500000:]]),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["code"] == "body_too_large"
    assert config_service.read()["revision"] == 1


def test_bot_environment_observation_and_effective_parameters(client, config_service):
    login(client)
    document = config_service.read()["document"]
    document["providers"] = [provider()]
    config_service.replace(document, 1)
    unavailable = client.get(f"{BASE}/environment").json()
    assert not unavailable["available"]
    assert unavailable["variables"] == [{"name": "MODEL_KEY", "configured": None}]
    boot = config_service.register_bot_boot("boot", 1)
    config_service.report_bot(boot, 1, {"environment": [{"name": "MODEL_KEY", "configured": True}]})
    assert client.get(f"{BASE}/environment").json()["variables"][0]["configured"] is True
    effective = client.get(f"{BASE}/providers/p/effective", params={"model": "owner/model"})
    assert effective.status_code == 200
    assert effective.json()["parameters"]["temperature"]["value"] == 0
    assert effective.json()["parameters"]["temperature"]["source"] == "model"


def test_public_openapi_matches_runtime_registry():
    from pathlib import Path
    from quickquip.app.web.llm_configuration_schema import configuration_openapi

    artifact = Path(__file__).resolve().parents[3] / "docs/dev/llm-configuration.openapi.json"
    expected = json.loads(artifact.read_text(encoding="utf-8"))
    generated = json.loads(json.dumps(configuration_openapi()))
    assert generated == expected
    assert generated["components"]["schemas"]["ConfigDocument"]["properties"]["providers"]
    for path, verbs in generated["paths"].items():
        for method, operation in verbs.items():
            if method in ("get", "post", "put", "patch", "delete"):
                assert operation["security"] == [{"AdminSession": []}]
                assert operation["responses"]["409"]["content"]["application/json"]["schema"][
                    "$ref"
                ]


def test_parameter_patch_keeps_omitted_values_and_replaces_extra_body(client, config_service):
    login(client)
    document = config_service.read()["document"]
    entry = provider()
    entry["parameters"] = {
        "temperature": 0.5,
        "stream_enabled": True,
        "extra_body": {"old": {"inner": 1}},
    }
    document["providers"] = [entry]
    document["pricing"] = [{"provider_id": "p", "model": "owner/model", "input_per_mtok": 0}]
    config_service.replace(document, 1)
    response = client.patch(
        f"{BASE}/providers/p",
        json={
            "expected_draft_revision": 2,
            "fields": {"parameters": {"temperature": None, "extra_body": {}}},
        },
    )
    assert response.status_code == 200
    parameters = response.json()["document"]["providers"][0]["parameters"]
    assert parameters["stream_enabled"] is True
    assert parameters["temperature"] is None
    assert parameters["extra_body"] == {}
    detail = client.get(f"{BASE}/providers/p").json()
    assert detail["pricing"][0]["provider_id"] == "p"
    assert detail["effective_parameters"]["owner/model"]["stream_enabled"]["source"] == "provider"


def test_note_endpoint_labels_draft_and_snapshots(client, config_service):
    login(client)
    response = client.put(f"{BASE}/note", json={"source": "draft", "note": "  首版\n基线  "})
    assert response.status_code == 200
    body = response.json()
    assert body["draft_version"]["note"] == "首版 基线"
    assert body["published_version"] == body["draft_version"]
    assert isinstance(body["draft_version"]["saved_at"], float)
    history = client.get(f"{BASE}/history").json()["snapshots"]
    assert history[0]["note"] == "首版 基线"
    assert client.put(f"{BASE}/note", json={"source": "99", "note": "x"}).status_code == 404
    assert client.put(f"{BASE}/note", json={"note": "x" * 121}).status_code == 422
    providers = client.get(f"{BASE}/providers?source=published").json()
    assert providers["version"]["note"] == "首版 基线"


def test_configuration_maintenance_reports_conflict_without_saving(client, config_service):
    from quickquip.config_sync.state import State
    login(client)
    before = config_service.read()
    State(config_service.path.parent).write(
        "maintenance.json", {"operation": "a" * 32, "token": "synthetic"}
    )
    response = client.put(BASE, json={'expected_draft_revision': before['revision'],
                                      'document': before['document']})
    assert response.status_code == 409
    assert response.json()['code'] == 'configuration_busy'
    assert config_service.read() == before
