"""Scope preference updates remain separate from conversation storage."""

import pytest
from quickquip.llm.config_service import ConfigService


@pytest.fixture
def store(tmp_path):
    service = ConfigService(tmp_path / "config.db")
    service.initialize()
    return service.scope_settings


# ── group_settings 域 ─────────────────────────────────────────────────────────


def test_group_settings_get_missing_returns_empty(store) -> None:
    from quickquip.llm.store import GroupSettingsOverride

    override = store.get_group_settings(9999)
    assert isinstance(override, GroupSettingsOverride)
    assert override.enabled is None
    assert override.provider_id is None


def test_group_settings_update_and_readback(store) -> None:
    store.update_group_settings(3001, enabled=True, provider_id="openai", model="gpt-4")
    override = store.get_group_settings(3001)
    assert override.enabled is True
    assert override.provider_id == "openai"
    assert override.model == "gpt-4"

    # 再次 update 部分字段
    store.update_group_settings(3001, model="gpt-4o")
    override = store.get_group_settings(3001)
    assert override.model == "gpt-4o"
    # 之前设的 enabled 应保留
    assert override.enabled is True


def test_group_settings_bool_conversion(store) -> None:
    store.update_group_settings(3002, enabled=False, memory_enabled=True, allow_at=False)
    override = store.get_group_settings(3002)
    assert override.enabled is False
    assert override.memory_enabled is True
    assert override.allow_at is False


def test_group_settings_agent_delivery_roundtrip(store) -> None:
    store.update_group_settings(3003, agent_delivery_intermediate_enabled=True)
    override = store.get_group_settings(3003)
    assert override.agent_delivery_intermediate_enabled is True
    assert override.agent_delivery_final_enabled is None
    store.update_group_settings(3003, agent_delivery_final_enabled=False)
    override = store.get_group_settings(3003)
    assert override.agent_delivery_intermediate_enabled is True
    assert override.agent_delivery_final_enabled is False
    # 显式 None 清空单域覆盖（另一域不受影响，回到跟随全局默认）
    store.update_group_settings(3003, agent_delivery_intermediate_enabled=None)
    override = store.get_group_settings(3003)
    assert override.agent_delivery_intermediate_enabled is None
    assert override.agent_delivery_final_enabled is False


def test_group_settings_reasoning_effort_roundtrip(store) -> None:
    assert store.get_group_settings(3004).reasoning_effort is None

    store.update_group_settings(3004, reasoning_effort="high")
    assert store.get_group_settings(3004).reasoning_effort == "high"

    # 部分更新其他字段不清覆盖
    store.update_group_settings(3004, model="gpt-4o")
    assert store.get_group_settings(3004).reasoning_effort == "high"

    # 显式 None 清空覆盖（回到跟随 provider 配置档）
    store.update_group_settings(3004, reasoning_effort=None)
    assert store.get_group_settings(3004).reasoning_effort is None
