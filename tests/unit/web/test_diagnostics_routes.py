"""Model diagnostics are immutable bot operations and never run in Web."""

from __future__ import annotations

import pytest

from quickquip.app.web.routes import diagnostics
from quickquip.app.web.routes.llm_configuration import ProbeBody
from quickquip.llm.config_document import ConfigError


def test_browser_diagnostics_payloads_queue_and_recover_same_operation(config_service):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from quickquip.app.web.routes import llm_configuration

    draft = config_service.read()
    draft["document"]["providers"] = [{
        "id": "p", "protocol": "openai", "base_url": "https://example.test/v1",
        "api_key_env": "SYNTHETIC_KEY", "default_model": "owner/default",
        "models": [{"model": "first"}, {"model": "owner/default"}],
    }]
    config_service.replace(draft["document"], draft["revision"])
    config_service.apply(2, "publish-targets")
    publication = config_service.tasks.claim("bot")
    config_service.publish(publication["id"], publication["claim_token"])
    config_service.tasks.finish(publication["id"], publication["claim_token"])

    app = FastAPI()
    app.include_router(diagnostics.router, prefix="/ops/api")
    app.include_router(llm_configuration.router, prefix="/ops/api")
    with TestClient(app) as client:
        snapshot = client.get("/ops/api/diagnostics/providers").json()
        assert snapshot["revision"] == 2
        assert snapshot["providers"][0]["default_model"] == "owner/default"
        body = {
            "source": snapshot["revision"], "provider_id": "p", "model": "owner/default",
            "request_id": "browser-probe",
        }
        for endpoint in ("providers/probe", "sample-request"):
            if endpoint == "sample-request":
                body = {**body, "request_id": "browser-sample", "user_prompt": "synthetic input",
                        "system_prompt": "test", "stream": False, "max_output_tokens": 256}
            url = "/ops/api/diagnostics/" + endpoint
            queued = client.post(url, json=body)
            assert queued.status_code == 202
            queued = queued.json()
            assert queued["status"] == "queued"
            assert queued["result"] is None
            assert queued["may_charge"] and not queued["automatic_retry"]
            assert client.post(url, json=body).json()["id"] == queued["id"]
            claim = config_service.tasks.claim("bot")
            assert claim["id"] == queued["id"]
            operation_url = "/ops/api/llm-configuration/operations/" + queued["id"]
            assert client.get(operation_url).json()["status"] == "running"
            config_service.tasks.finish(claim["id"], claim["claim_token"], result={"text": "done"})
            completed = client.get(operation_url).json()
            assert completed["status"] == "succeeded"
            assert completed["result"] == {"text": "done"}
            # A lost submission response can be recovered after execution without creating work.
            assert client.post(url, json=body).json()["id"] == queued["id"]
            assert config_service.tasks.claim("bot") is None


def test_probe_queues_explicit_snapshot(config_service):
    draft = config_service.read()
    draft["document"]["providers"] = [
        {
            "id": "p",
            "protocol": "openai",
            "base_url": "https://example.com/v1",
            "api_key_env": "API_KEY",
            "default_model": "m",
            "models": [{"model": "m"}],
        }
    ]
    config_service.replace(draft["document"], 1)
    result = diagnostics.probe_providers(
        ProbeBody(source="draft", provider_id="p", model="m", request_id="probe")
    )
    assert result["status"] == "queued"
    assert result["kind"] == "probe"
    assert result["target_revision"] == 2
    assert result["may_charge"] and not result["automatic_retry"]
    assert config_service.status()["published_revision"] == 1


def test_probe_unknown_target_rejected(config_service):
    with pytest.raises(ConfigError) as exc:
        diagnostics.probe_providers(ProbeBody(provider_id="missing", model="m", request_id="probe"))
    assert exc.value.code in ("invalid_reference", "dependency_conflict")
    assert config_service.tasks.claim("bot") is None
