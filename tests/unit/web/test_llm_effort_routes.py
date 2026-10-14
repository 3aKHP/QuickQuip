"""Provider thinking defaults use revision checks and draft-only persistence."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from quickquip.app.web.routes import llm_effort as routes
from quickquip.llm.config_document import ConfigError


@pytest.fixture
def configured(config_service, monkeypatch):
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
    config_service.replace(draft["document"], draft["revision"])
    monkeypatch.setattr(routes.audit_logger, "log", lambda *a, **k: None)
    return config_service


def test_read_draft_effort_and_revision(configured):
    result = routes.get_llm_effort()
    assert result["revision"] == 2
    assert result["providers"] == [{"id": "p", "default_model": "m", "reasoning_effort": None}]


def test_save_effort_changes_draft_only(configured):
    result = routes.put_llm_effort(
        "p", routes.EffortBody(effort="high", expected_draft_revision=2), object()
    )
    assert result["effect"] == "saved_draft"
    assert configured.read()["document"]["providers"][0]["parameters"]["reasoning_effort"] == "high"
    assert configured.read("published")["revision"] == 1
    with pytest.raises(ConfigError) as exc:
        routes.put_llm_effort(
            "p", routes.EffortBody(effort="low", expected_draft_revision=2), object()
        )
    assert exc.value.code == "revision_conflict"


def test_null_inherits_and_empty_is_explicit(configured):
    result = routes.put_llm_effort(
        "p", routes.EffortBody(effort="", expected_draft_revision=2), object()
    )
    assert result["document"]["providers"][0]["parameters"]["reasoning_effort"] == ""
    result = routes.put_llm_effort(
        "p", routes.EffortBody(effort=None, expected_draft_revision=3), object()
    )
    assert result["document"]["providers"][0]["parameters"]["reasoning_effort"] is None


def test_validation_and_unknown_provider_do_not_save(configured):
    with pytest.raises(ValidationError):
        routes.EffortBody(effort="turbo", expected_draft_revision=2)
    with pytest.raises(ValidationError):
        routes.EffortBody(effort="high")
    with pytest.raises(ConfigError) as exc:
        routes.put_llm_effort(
            "missing", routes.EffortBody(effort="high", expected_draft_revision=2), object()
        )
    assert exc.value.code == "not_found"
    assert configured.read()["revision"] == 2
