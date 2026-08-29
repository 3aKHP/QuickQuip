"""Web Admin 根路径重定向测试（PR #155 / 验收发现 L2）。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from quickquip.app.web.app import _register_root_redirect


def test_root_redirects_to_ops_console():
    """裸 app 上注册重定向：GET / → 307 /ops/（hermetic，不触发 create_app 副作用）。"""
    app = FastAPI()
    _register_root_redirect(app)
    client = TestClient(app)

    resp = client.get("/", follow_redirects=False)

    assert resp.status_code == 307
    assert resp.headers["location"] == "/ops/"
