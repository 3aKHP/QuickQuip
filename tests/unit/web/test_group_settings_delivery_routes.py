"""group-settings 路由的交付两域字段：写入路由、默认投影与列表形状。"""
from __future__ import annotations

import sqlite3

import pytest

fastapi = pytest.importorskip("fastapi")

from quickquip.app.web.routes import group_settings as routes  # noqa: E402


def _patch_audit_noop(monkeypatch):
    monkeypatch.setattr(routes.audit_logger, "log", lambda *a, **k: None)


def test_options_defaults_carry_both_delivery_domains(monkeypatch, tmp_path):
    """options 投影携带两域全局默认。"""
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
    assert payload["defaults"]["agent_delivery_intermediate_enabled"] is True
    assert payload["defaults"]["agent_delivery_final_enabled"] is False
    assert "agent_delivery_enabled" not in payload["defaults"]


def test_options_defaults_empty_when_llm_toml_load_fails(monkeypatch, tmp_path):
    """读 llm.toml 抛异常时兜底空 defaults + 非空 load_error（不向上抛）。"""
    def _boom(path):
        raise RuntimeError("boom")

    monkeypatch.setattr(routes, "load_llm_config", _boom)
    monkeypatch.setattr(routes, "_LLM_TOML", tmp_path / "llm.toml")

    payload = routes.get_options()
    assert payload["providers"] == []
    assert payload["personas"] == []
    assert payload["defaults"] == {}
    assert "boom" in payload["load_error"]


def test_put_body_fields_route_to_store(monkeypatch, tmp_path):
    """PUT body 的两域字段进入 store 写入；旧键名被 Pydantic 静默忽略。"""
    calls: list[tuple[str, dict]] = []

    class FakeStore:
        def update_group_settings(self, group_id, **fields):
            calls.append((group_id, fields))

    monkeypatch.setattr(routes, "_store", lambda: FakeStore())
    monkeypatch.setattr(routes, "_DB", tmp_path / "llm.db")
    _patch_audit_noop(monkeypatch)

    body = routes.GroupSettingsBody(
        agent_delivery_intermediate_enabled=True, agent_delivery_final_enabled=False
    )
    assert routes.put_group_settings("10001", body, object()) == {"ok": True}
    assert calls == [("10001", {"agent_delivery_intermediate_enabled": True, "agent_delivery_final_enabled": False})]

    # 旧键名被 Pydantic 静默忽略（不落库、不报错）：旧前端 bundle 只带旧键
    # 提交 → payload 为空 → 400；与其他字段一起提交 → 其余字段落库、开关不动。
    legacy_body = routes.GroupSettingsBody(agent_delivery_enabled=True)
    assert legacy_body.model_dump(exclude_unset=True) == {}


def test_list_group_settings_projects_both_delivery_domains(monkeypatch, tmp_path):
    """列表 SELECT/投影包含两域新列：预置行的取值原样出现在条目里。"""
    db_path = tmp_path / "llm.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE group_settings (
            group_id TEXT PRIMARY KEY,
            enabled INTEGER,
            memory_enabled INTEGER,
            auto_memory_enabled INTEGER,
            agent_delivery_enabled INTEGER,
            agent_delivery_intermediate_enabled INTEGER,
            agent_delivery_final_enabled INTEGER,
            provider_id TEXT,
            model TEXT,
            persona_id TEXT,
            trigger_prefix TEXT,
            allow_prefix INTEGER,
            allow_at INTEGER,
            history_limit INTEGER,
            updated_at TEXT NOT NULL
        );
        INSERT INTO group_settings (group_id, agent_delivery_intermediate_enabled, agent_delivery_final_enabled, updated_at)
        VALUES ('10001', 1, 0, '2026-09-11T00:00:00+00:00');
        """
    )
    conn.commit()
    conn.close()

    import quickquip.app.message_pipeline as message_pipeline
    monkeypatch.setattr(routes, "_DB", db_path)
    monkeypatch.setattr(message_pipeline, "stats_tracker",
                        type("T", (), {"to_dict": staticmethod(lambda: {})})())

    payload = routes.list_group_settings()
    entry = next(g for g in payload["groups"] if g["group_id"] == "10001")
    assert entry["agent_delivery_intermediate_enabled"] is True
    assert entry["agent_delivery_final_enabled"] is False
