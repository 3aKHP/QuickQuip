"""应用级安全边界：API 文档端点不对外暴露，全部响应携带安全响应头。"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from quickquip.app.web import app as web_app


@pytest.fixture
def created_client(monkeypatch):
    monkeypatch.setattr(
        "quickquip.llm.client_fingerprints.catalog.get_catalog", lambda: None
    )
    from quickquip.app import message_pipeline

    monkeypatch.setattr(message_pipeline.tieba_service, "load", lambda: None)
    with TestClient(web_app.create_app()) as client:
        yield client


class TestApiDocsDisabled:
    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
    def test_docs_endpoints_not_exposed(self, created_client, path):
        assert created_client.get(path).status_code == 404


class TestSecurityHeaders:
    EXPECTED = {
        "content-security-policy": "default-src 'self'; img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
        "x-content-type-options": "nosniff",
        "referrer-policy": "no-referrer",
        "x-frame-options": "DENY",
    }

    def test_headers_on_api_responses(self, created_client):
        response = created_client.get("/ops/api/auth/me")
        assert response.status_code == 401
        for name, value in self.EXPECTED.items():
            assert response.headers.get(name) == value

    def test_headers_on_root_redirect(self, created_client):
        response = created_client.get("/", follow_redirects=False)
        assert response.status_code == 307
        for name, value in self.EXPECTED.items():
            assert response.headers.get(name) == value

    def test_headers_registered_on_bare_app(self):
        bare = FastAPI()
        web_app._register_security_headers(bare)

        @bare.get("/ping")
        def _ping():
            return {"ok": True}

        response = TestClient(bare).get("/ping")
        for name, value in self.EXPECTED.items():
            assert response.headers.get(name) == value
