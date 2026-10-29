"""Private runtime controls preserve preferences and history across parameter resets."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from quickquip.app.web.routes import group_settings as routes
from quickquip.llm.store import LLMStore


def test_private_state_and_preferences_have_independent_write_targets(
    config_service,
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "chat.db"
    monkeypatch.setattr(routes, "_DB", path)
    monkeypatch.setattr(routes.audit_logger, "log", lambda *args, **kwargs: None)
    store = LLMStore(path)
    store.start_private_chat_session("67890")
    store.append_conversation_message("private:67890", "67890", "user", "keep this history")
    config_service.scope_settings.update_group_settings("private:67890", history_limit=12)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.put("/private-sessions/67890/state", json={"active": False})
        assert response.status_code == 200
        assert not store.private_chat_active("67890")
        assert config_service.scope_settings.get_group_settings("private:67890").history_limit == 12
        assert (
            client.put("/group-settings/private:67890", json={"enabled": True}).status_code == 422
        )
        assert client.put("/private-sessions/67890/state", json={"active": True}).status_code == 200
        assert client.delete("/group-settings/private:67890").status_code == 200
        assert store.private_chat_active("67890")
        assert (
            config_service.scope_settings.get_group_settings("private:67890").history_limit is None
        )
        assert store.count_conversation_messages("private:67890") == 1
