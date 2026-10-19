"""贴吧同步路由：POST 触发同步并回传 SSE 进度流，GET 不再可用（无副作用）。"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from quickquip.app.web.routes import tieba


class _FakeTiebaService:
    def __init__(self):
        self.sync_calls: list[dict] = []

    async def sync_now(self, *, force, forum_keyword, on_progress):
        self.sync_calls.append({"force": force, "forum_keyword": forum_keyword})
        if on_progress:
            on_progress("▶ 开始同步")
            on_progress("✓ 同步完成")
        return {"results": [], "count": 0, "status": "ok", "message": ""}


@pytest.fixture
def service(monkeypatch):
    fake = _FakeTiebaService()
    monkeypatch.setattr("quickquip.app.message_pipeline.tieba_service", fake)
    return fake


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(tieba.router, prefix="/ops/api")
    with TestClient(app) as result:
        yield result


def test_post_triggers_sync_and_streams_progress(client, service):
    response = client.post("/ops/api/tieba/sync", params={"forum": "测试"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data: ▶ 开始同步" in response.text
    assert "data: [done]" in response.text
    assert service.sync_calls == [{"force": True, "forum_keyword": "测试"}]


def test_get_sync_route_does_not_exist(client, service):
    response = client.get("/ops/api/tieba/sync")

    assert response.status_code == 405
    assert service.sync_calls == []
