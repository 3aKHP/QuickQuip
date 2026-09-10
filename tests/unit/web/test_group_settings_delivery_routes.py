"""group-settings 路由的交付两域字段：写入路由、默认投影与列表形状。"""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")

from quickquip.app.web.routes import group_settings as routes  # noqa: E402


def _patch_audit_noop(monkeypatch):
    monkeypatch.setattr(routes.audit_logger, "log", lambda *a, **k: None)


def test_options_defaults_carry_both_delivery_domains(monkeypatch, tmp_path):
    """options 投影携带两域全局默认（读 llm.toml 失败时空对象兜底不回归）。"""
    import types

    fake_runtime = types.SimpleNamespace(
        enabled=True, memory_enabled=True, auto_memory_enabled=False,
        agent_delivery_intermediate_enabled=True, agent_delivery_final_enabled=False,
        default_provider="p1", default_persona=None, history_limit=10,
    )
    fake_cfg = types.SimpleNamespace(
        runtime=fake_runtime,
        providers={},
        personas={},
        triggers=types.SimpleNamespace(default_prefix="/", allow_prefix=True, allow_at=True),
        load_error=None,
    )
    monkeypatch.setattr(routes, "load_llm_config", lambda path: fake_cfg)
    monkeypatch.setattr(routes, "_LLM_TOML", tmp_path / "llm.toml")

    payload = routes.get_options()
    assert payload["defaults"]["agent_delivery_intermediate"] is True
    assert payload["defaults"]["agent_delivery_final"] is False
    assert "agent_delivery_enabled" not in payload["defaults"]


def test_put_body_fields_route_to_store(monkeypatch, tmp_path):
    """PUT body 的两域字段进入 store 写入；旧键名被 Pydantic 拒绝。"""
    calls: list[tuple[str, dict]] = []

    class FakeStore:
        def update_group_settings(self, group_id, **fields):
            calls.append((group_id, fields))

    monkeypatch.setattr(routes, "_store", lambda: FakeStore())
    monkeypatch.setattr(routes, "_DB", tmp_path / "llm.db")
    _patch_audit_noop(monkeypatch)

    body = routes.GroupSettingsBody(
        agent_delivery_intermediate=True, agent_delivery_final=False
    )
    assert routes.put_group_settings("10001", body, object()) == {"ok": True}
    assert calls == [("10001", {"agent_delivery_intermediate": True, "agent_delivery_final": False})]

    # 旧键名被 Pydantic 静默忽略（旧前端 bundle 对新后端不炸、不误写）
    legacy_body = routes.GroupSettingsBody(agent_delivery_enabled=True)
    assert legacy_body.model_dump(exclude_unset=True) == {}
