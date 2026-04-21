"""TOML config supports ${VAR:-default} env expansion in selected fields."""
from __future__ import annotations

import textwrap
from pathlib import Path

import quickquip.llm.service as llm_runtime_module


CONFIG_WITH_ENV_VARS = textwrap.dedent(
    """
    [runtime]
    enabled = "${QQ_TEST_ENABLED:-true}"
    default_provider = "openai-main"
    default_persona = "default"
    tool_calling_enabled = "${QQ_TOOL_CALLING_ENABLED:-true}"

    [mcp]
    enabled = "${QQ_MCP_ENABLED:-true}"

    [[mcp.servers]]
    id = "expand"
    transport = "docker"
    enabled = "${QQ_MCP_SERVER_ENABLED:-true}"
    image = "ghcr.io/example/server:latest"
    mounts = ["${QQ_MCP_MOUNT_ONE:-/data/one:/mnt/one:ro}", "${QQ_MCP_MOUNT_TWO:-}"]

    [[personas]]
    id = "default"
    display_name = "默认人格"
    system_prompt = "你是测试人格。"

    [[providers]]
    id = "openai-main"
    protocol = "openai"
    base_url = "https://example.test/v1"
    api_key_env = "OPENAI_API_KEY"
    default_model = "gpt-test"
    models = ["gpt-test"]
    """
).strip()


def test_env_expand_with_explicit_values(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "llm.toml"
    config_path.write_text(CONFIG_WITH_ENV_VARS, encoding="utf-8")

    monkeypatch.setenv("QQ_TEST_ENABLED", "true")
    monkeypatch.setenv("QQ_TOOL_CALLING_ENABLED", "true")
    monkeypatch.setenv("QQ_MCP_ENABLED", "true")
    monkeypatch.setenv("QQ_MCP_SERVER_ENABLED", "true")

    loaded = llm_runtime_module.load_llm_config(config_path)
    assert loaded.runtime.enabled is True
    assert loaded.runtime.tool_calling_enabled is True
    assert loaded.mcp.enabled is True
    assert loaded.mcp.servers[0].enabled is True
    # Empty default ${VAR:-} expands to empty string and is filtered from mounts
    assert loaded.mcp.servers[0].mounts == ["/data/one:/mnt/one:ro"]


def test_env_expand_falls_back_to_defaults(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "llm.toml"
    config_path.write_text(CONFIG_WITH_ENV_VARS, encoding="utf-8")

    for var in (
        "QQ_TEST_ENABLED",
        "QQ_TOOL_CALLING_ENABLED",
        "QQ_MCP_ENABLED",
        "QQ_MCP_SERVER_ENABLED",
        "QQ_MCP_MOUNT_ONE",
        "QQ_MCP_MOUNT_TWO",
    ):
        monkeypatch.delenv(var, raising=False)

    loaded = llm_runtime_module.load_llm_config(config_path)
    assert loaded.runtime.enabled is True
    assert loaded.mcp.servers[0].mounts == ["/data/one:/mnt/one:ro"]
