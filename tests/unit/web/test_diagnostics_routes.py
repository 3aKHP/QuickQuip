"""Model diagnostics are immutable bot operations and never run in Web."""

from __future__ import annotations

import pytest

from quickquip.app.web.routes import diagnostics
from quickquip.app.web.routes.llm_configuration import ProbeBody
from quickquip.llm.config_document import ConfigError


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
