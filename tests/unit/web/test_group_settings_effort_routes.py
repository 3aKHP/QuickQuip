"""group-settings 路由的思考档位字段：options 投影、PUT 校验与列表投影。"""

from __future__ import annotations


import pytest

fastapi = pytest.importorskip("fastapi")

from pydantic import ValidationError  # noqa: E402

from quickquip.app.web.routes import group_settings as routes  # noqa: E402


def test_options_providers_carry_reasoning_effort(monkeypatch, tmp_path):
    """options 的 providers 投影携带各 provider 配置档（供前端「跟随」提示）。"""
    import types

    fake_providers = {
        "p1": types.SimpleNamespace(
            id="p1",
            default_model="m1",
            models=["m1"],
            reasoning_effort="high",
        ),
        "p2": types.SimpleNamespace(
            id="p2",
            default_model="m2",
            models=["m2"],
            reasoning_effort="",
        ),
    }
    fake_cfg = types.SimpleNamespace(
        runtime=types.SimpleNamespace(
            enabled=True,
            memory_enabled=True,
            auto_memory_enabled=False,
            agent_delivery_intermediate_enabled=True,
            agent_delivery_final_enabled=False,
            default_provider="p1",
            default_persona=None,
            history_limit=10,
        ),
        providers=fake_providers,
        personas={},
        triggers=types.SimpleNamespace(default_prefix="/", allow_prefix=True, allow_at=True),
        load_error=None,
    )
    monkeypatch.setattr(routes, "compile_document", lambda document, **kwargs: fake_cfg)

    payload = routes.get_options()
    efforts = {p["id"]: p["reasoning_effort"] for p in payload["providers"]}
    assert efforts == {"p1": "high", "p2": ""}


def test_put_reasoning_effort_routes_to_store_and_validates(monkeypatch, tmp_path):
    """PUT 的 reasoning_effort 透传落库；显式 null 清覆盖；非法档位 422（校验拒绝）。"""
    calls: list[tuple[str, dict]] = []
    audits: list[dict] = []

    class FakeStore:
        def update_group_settings(self, group_id, **fields):
            calls.append((group_id, fields))

    repository = routes.get_config_service().scope_settings
    original_update = repository.update_group_settings
    def update(group_id, **fields):
        calls.append((group_id, fields))
        return original_update(group_id, **fields)
    monkeypatch.setattr(repository, "update_group_settings", update)
    monkeypatch.setattr(routes, "_DB", tmp_path / "llm.db")
    monkeypatch.setattr(
        routes.audit_logger,
        "log",
        lambda request, **kwargs: audits.append(kwargs),
    )

    body = routes.GroupSettingsBody(reasoning_effort="high")
    assert routes.put_group_settings("10001", body, object()) == {"ok": True}
    assert calls == [("10001", {"reasoning_effort": "high"})]
    assert audits == [
        {
            "action": "update",
            "target_type": "group_setting",
            "target_id": "10001",
            "summary_after": {"fields": ["reasoning_effort"]},
        }
    ]

    # 显式 null 与未发送的区分：null 进 payload（清覆盖），缺省不进 payload
    clear_body = routes.GroupSettingsBody(reasoning_effort=None)
    assert clear_body.model_dump(exclude_unset=True) == {"reasoning_effort": None}
    assert routes.put_group_settings("10001", clear_body, object()) == {"ok": True}
    assert calls[-1] == ("10001", {"reasoning_effort": None})
    assert len(audits) == 2

    empty_body = routes.GroupSettingsBody()
    assert "reasoning_effort" not in empty_body.model_dump(exclude_unset=True)

    for bogus in ("turbo", "HIGH", " "):
        with pytest.raises(ValidationError):
            routes.GroupSettingsBody(reasoning_effort=bogus)
    # 校验拒绝不触发落库与审计
    assert len(calls) == 2
    assert len(audits) == 2


def test_list_group_settings_projects_reasoning_effort(monkeypatch, tmp_path):
    """列表 SELECT/投影包含 reasoning_effort：预置行的取值原样出现在条目里。"""
    repository = routes.get_config_service().scope_settings
    repository.update_group_settings("10001", reasoning_effort="xhigh")
    repository.update_group_settings("10002", reasoning_effort=None)

    import quickquip.app.message_pipeline as message_pipeline

    monkeypatch.setattr(
        message_pipeline, "stats_tracker", type("T", (), {"to_dict": staticmethod(lambda: {})})()
    )

    payload = routes.list_group_settings()
    entries = {g["group_id"]: g for g in payload["groups"]}
    assert entries["10001"]["reasoning_effort"] == "xhigh"
    assert entries["10002"]["reasoning_effort"] is None
