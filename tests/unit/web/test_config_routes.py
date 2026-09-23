from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from quickquip.app.web.routes import config


def _mock_request():
    req = MagicMock()
    req.client.host = "127.0.0.1"
    return req


def _patch_config_dir(monkeypatch, tmp_path: Path) -> Path:
    base = tmp_path / "config"
    base.mkdir()
    monkeypatch.setattr(config, "_CONFIG_DIR", base)
    return base


def test_list_configs_does_not_expose_sensitive_words(monkeypatch, tmp_path):
    _patch_config_dir(monkeypatch, tmp_path)

    result = config.list_configs()

    keys = {item["key"] for item in result["configs"]}
    filenames = {item["filename"] for item in result["configs"]}
    assert "sensitive_words" not in keys
    assert "sensitive_words.toml" not in filenames


def test_sensitive_words_config_key_is_not_readable(monkeypatch, tmp_path):
    _patch_config_dir(monkeypatch, tmp_path)

    with pytest.raises(HTTPException) as exc:
        config.get_config("sensitive_words")

    assert exc.value.status_code == 404


def test_sensitive_words_config_key_is_not_writable(monkeypatch, tmp_path):
    _patch_config_dir(monkeypatch, tmp_path)

    with pytest.raises(HTTPException) as exc:
        config.put_config(
            "sensitive_words",
            config.ConfigBody(content="[block]\nwords = [\"secret\"]\n"),
            _mock_request(),
        )

    assert exc.value.status_code == 404
    assert not (tmp_path / "config" / "sensitive_words.toml").exists()


def test_put_awakening_config_queues_reload(monkeypatch, tmp_path):
    base = _patch_config_dir(monkeypatch, tmp_path)
    captured: list[str] = []
    monkeypatch.setattr(
        config.action_queue, "enqueue",
        lambda action_type: captured.append(action_type) or {"id": "a1"},
    )
    monkeypatch.setattr(config.audit_logger, "log", lambda *args, **kwargs: None)

    result = config.put_config(
        "awakening",
        config.ConfigBody(content="[awakening.defaults]\nfallback_probability = 0.1\n"),
        _mock_request(),
    )

    assert result["effect"] == "auto_reloading"
    assert captured == ["awakening_reload"]
    assert (base / "awakening.toml").exists()


def test_put_chat_rules_config_queues_rules_reload(monkeypatch, tmp_path):
    _patch_config_dir(monkeypatch, tmp_path)
    captured: list[str] = []
    monkeypatch.setattr(
        config.action_queue, "enqueue",
        lambda action_type: captured.append(action_type) or {"id": "r1"},
    )
    monkeypatch.setattr(config.audit_logger, "log", lambda *args, **kwargs: None)

    result = config.put_config(
        "chat_rules",
        config.ConfigBody(content="[text_rules]\nname = 'x'\n"),
        _mock_request(),
    )

    assert result["effect"] == "auto_reloading"
    assert captured == ["rules_reload"]


def test_put_llm_config_does_not_queue_reload(monkeypatch, tmp_path):
    """llm 改动不自动 reload——reload_runtime 含探活会静默扣费（opt-in）。"""
    _patch_config_dir(monkeypatch, tmp_path)
    captured: list[str] = []
    monkeypatch.setattr(
        config.action_queue, "enqueue",
        lambda action_type: captured.append(action_type) or {"id": "x1"},
    )
    monkeypatch.setattr(config.audit_logger, "log", lambda *args, **kwargs: None)

    result = config.put_config(
        "llm",
        config.ConfigBody(content="[runtime]\nenabled = true\n"),
        _mock_request(),
    )

    assert result["effect"] == "manual_reload"
    assert captured == []  # 不入队，避免静默探活扣费


@pytest.mark.parametrize("key", ["games", "generation", "niuniu_text", "niuniu_text_safe"])
def test_put_restart_needed_configs_do_not_queue_reload(monkeypatch, tmp_path, key):
    _patch_config_dir(monkeypatch, tmp_path)
    captured: list[str] = []
    monkeypatch.setattr(
        config.action_queue, "enqueue",
        lambda action_type: captured.append(action_type) or {"id": "g1"},
    )
    monkeypatch.setattr(config.audit_logger, "log", lambda *args, **kwargs: None)

    result = config.put_config(
        key,
        config.ConfigBody(content="[section]\nkey = 'value'\n"),
        _mock_request(),
    )

    assert result["effect"] == "restart_needed"
    assert captured == []
