from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
HTTPException = fastapi.HTTPException

from quickquip.app.web.routes import llm_runtime  # noqa: E402


def test_health_check_is_queued_without_loading_llm_service(monkeypatch):
    captured: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        llm_runtime.action_queue,
        "enqueue",
        lambda action_type, payload=None: captured.append((action_type, payload or {})) or {"id": "h1"},
    )
    monkeypatch.setattr(llm_runtime.audit_logger, "log", lambda *args, **kwargs: None)

    result = llm_runtime.queue_health_check(llm_runtime.HealthBody(verbose=True), object())

    assert result["queued"] is True
    assert captured == [("health_check", {"verbose": True, "scope_key": "__web_admin__"})]


def test_health_check_accepts_explicit_scope(monkeypatch):
    captured: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        llm_runtime.action_queue,
        "enqueue",
        lambda action_type, payload=None: captured.append((action_type, payload or {})) or {"id": "h1"},
    )
    monkeypatch.setattr(llm_runtime.audit_logger, "log", lambda *args, **kwargs: None)

    llm_runtime.queue_health_check(llm_runtime.HealthBody(scope_key="private:123456", verbose=False), object())

    assert captured == [("health_check", {"verbose": False, "scope_key": "private:123456"})]


def test_health_check_rejects_invalid_scope():
    with pytest.raises(HTTPException) as exc:
        llm_runtime.queue_health_check(llm_runtime.HealthBody(scope_key="../config"), object())

    assert exc.value.status_code == 422
