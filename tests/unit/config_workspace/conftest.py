"""Isolated project and initialized workspace for the qqconf contract."""

import pytest

from quickquip.configuration.activity import service_guard
from quickquip.config_workspace.service import Workspace
from quickquip.llm.config_service import ConfigService


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    service = ConfigService(root / "config/managed/config.db")
    service.initialize()
    document = service.read()["document"]
    document["providers"] = [
        {
            "id": "alpha",
            "protocol": "openai",
            "base_url": "https://example.test/v1",
            "api_key_env": "SYNTHETIC_API_KEY",
            "default_model": "first",
            "models": [{"model": "first"}, {"model": "second"}],
            "parameters": {
                "temperature": 1.0,
                "timeout_seconds": 30.0,
                "extra_body": {
                    "nullable": None,
                    "large": 2**80,
                    "object": {"__quickquip_value__": "null"},
                },
            },
        }
    ]
    service.replace(document, 1)
    (root / ".env").write_text(
        '# credentials\nSYNTHETIC_API_KEY="private-sentinel" # keep\nPORT=5000\n'
    )
    (root / "config/chat_rules.toml").write_text("# rules\n[defaults]\nweight=1\nchance=0.5\n")
    for role in ("bot", "web"):
        with service_guard(root, role):
            pass
    return root, service


@pytest.fixture
def workspace(project):
    root, _ = project
    workspace = Workspace(root=root)
    workspace.unpack()
    return workspace
