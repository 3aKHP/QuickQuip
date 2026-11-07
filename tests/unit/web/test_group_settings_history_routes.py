"""group-settings 路由的群历史开关（#72）：llm.db 分流、三态与私聊拒绝。"""

from __future__ import annotations


import pytest

fastapi = pytest.importorskip("fastapi")

from quickquip.app.web.routes import group_settings as routes  # noqa: E402
from quickquip.llm.store import LLMStore  # noqa: E402


def _patch_audit_noop(monkeypatch):
    monkeypatch.setattr(routes.audit_logger, "log", lambda *a, **k: None)


def test_options_defaults_carry_group_history(monkeypatch):
    import types

    fake_cfg = types.SimpleNamespace(
        runtime=types.SimpleNamespace(
            enabled=True, memory_enabled=True, auto_memory_enabled=False,
            agent_delivery_intermediate_enabled=False, agent_delivery_final_enabled=False,
            default_provider="p1", default_persona=None, history_limit=10,
        ),
        providers={},
        personas={},
        triggers=types.SimpleNamespace(default_prefix="/", allow_prefix=True, allow_at=True),
        group_history=types.SimpleNamespace(enabled=True),
        load_error=None,
    )
    monkeypatch.setattr(routes, "compile_document", lambda document, **kwargs: fake_cfg)
    payload = routes.get_options()
    assert payload["defaults"]["history_enabled"] is True


def test_put_history_flag_routes_to_llm_store(monkeypatch, tmp_path):
    monkeypatch.setattr(routes, "_DB", tmp_path / "llm.db")
    _patch_audit_noop(monkeypatch)

    repository = routes.get_config_service().scope_settings
    monkeypatch.setattr(
        repository, "update_group_settings",
        lambda *a, **k: pytest.fail("history 字段不得进入 config.db 写路径"),
    )

    body = routes.GroupSettingsBody(history_enabled=True)
    assert routes.put_group_settings("10001", body, object()) == {"ok": True}
    assert LLMStore(tmp_path / "llm.db").get_group_history_flag("10001") is True

    # 显式 null = 清除本群覆盖（回到继承全局）
    clear = routes.GroupSettingsBody(history_enabled=None)
    routes.put_group_settings("10001", clear, object())
    assert LLMStore(tmp_path / "llm.db").get_group_history_flag("10001") is None

    # 混合提交：历史字段走 llm.db，其余字段照常走 config.db
    seen: list[dict] = []

    def _capture(group_id, **fields):
        seen.append(fields)

    monkeypatch.setattr(repository, "update_group_settings", _capture)
    mixed = routes.GroupSettingsBody(history_enabled=False, memory_enabled=True)
    routes.put_group_settings("10002", mixed, object())
    assert seen == [{"memory_enabled": True}]
    assert LLMStore(tmp_path / "llm.db").get_group_history_flag("10002") is False


def test_put_history_flag_rejected_for_private_scope(monkeypatch, tmp_path):
    monkeypatch.setattr(routes, "_DB", tmp_path / "llm.db")
    _patch_audit_noop(monkeypatch)
    body = routes.GroupSettingsBody(history_enabled=True)
    with pytest.raises(fastapi.HTTPException) as exc:
        routes.put_group_settings("private:10001", body, object())
    assert exc.value.status_code == 422


def test_list_and_get_merge_history_flags(monkeypatch, tmp_path):
    monkeypatch.setattr(routes, "_DB", tmp_path / "llm.db")
    store = LLMStore(tmp_path / "llm.db")
    store.set_group_history_flag("10001", True)

    import quickquip.app.message_pipeline as message_pipeline

    monkeypatch.setattr(
        message_pipeline, "stats_tracker",
        type("T", (), {"to_dict": staticmethod(lambda: {"10001": {}})})(),
    )

    payload = routes.list_group_settings()
    entry = next(g for g in payload["groups"] if g["group_id"] == "10001")
    assert entry["history_enabled"] is True

    single = routes.get_group_settings("10001")
    assert single["history_enabled"] is True
    # 无记录的群 → None（继承全局）
    assert routes.get_group_settings("10003")["history_enabled"] is None
