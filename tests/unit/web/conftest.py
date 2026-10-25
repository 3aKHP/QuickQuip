"""Web regressions always use isolated LLM configuration databases."""

import importlib

import pytest

from quickquip.llm.config_service import ConfigService


@pytest.fixture(autouse=True)
def config_service(monkeypatch, tmp_path):
    service = ConfigService(tmp_path / "llm_config.db")
    service.initialize()
    import quickquip.llm.config_service as service_module

    monkeypatch.setattr(service_module, "get_config_service", lambda: service)
    for name in (
        "llm_configuration",
        "llm_effort",
        "diagnostics",
        "group_settings",
        "mcp_dashboard",
    ):
        module = importlib.import_module(f"quickquip.app.web.routes.{name}")
        monkeypatch.setattr(module, "get_config_service", lambda: service)
        if name == "group_settings":
            monkeypatch.setattr(module, "_DB", tmp_path / "chat.db")
    return service
