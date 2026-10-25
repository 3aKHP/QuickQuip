import pytest

from quickquip.config_sync.endpoint import Endpoint
from quickquip.config_workspace.service import Workspace
from quickquip.llm.config_document import empty_document
from quickquip.llm.config_service import ConfigService


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "project"
    (root / "config").mkdir(parents=True)
    service = ConfigService(root / "config/managed/config.db")
    service.initialize()
    document = empty_document()
    document["style_profiles"] = {"general": "中文提示\n第二行\n"}
    document["providers"] = [
        {
            "id": "alpha",
            "protocol": "openai",
            "base_url": "https://example.invalid/v1",
            "api_key_env": "TEST_API_KEY",
            "default_model": "first",
            "parameters": {
                "timeout_seconds": 30.0,
                "temperature": 1.0,
                "style_profile": "general",
                "extra_body": {
                    "nullable": None,
                    "object": {"__quickquip_value__": "null"},
                    "number": 2**80,
                    "mixed": [None, False, 0, {}, []],
                },
            },
            "models": [
                {"model": "first", "context_window": None},
                {"model": "second", "context_window": 32000},
            ],
            "aliases": [{"alias": "one", "model": "first"}],
        }
    ]
    document["routes"]["daily_summary"] = [
        {"provider_id": "alpha", "model": "second"},
        "@default",
        {"provider_id": "alpha", "model": "first"},
    ]
    document["pricing"] = [
        {
            "provider_id": "alpha",
            "model": "first",
            "input_per_mtok": 1.0,
            "output_per_mtok": 2,
            "cache_read_per_mtok": None,
        }
    ]
    service.replace(document, 1)
    (root / "config/admins.toml").write_bytes(b"# original bytes\r\n")
    value = Workspace(tmp_path / "workspace", root)
    value.initialize()
    return value


@pytest.fixture
def source(workspace):
    return Endpoint(workspace.endpoint.root)


def edit_value(workspace, name, transform):
    from quickquip.config_workspace.codec import load_value, render_value

    path = workspace.storage.directory / name
    original = path.read_bytes()
    value = load_value(original, name)
    changed = transform(value)
    path.write_bytes(render_value(value if changed is None else changed, original))
    return path


def provider_file(workspace):
    from quickquip.config_workspace.layout import read_tree

    return read_tree(workspace.storage.directory).manifest["providers"][0]


def change_source(source, timeout):
    state = source.service.read()
    state["document"]["providers"][0]["parameters"]["timeout_seconds"] = timeout
    return source.service.replace(state["document"], state["revision"])
