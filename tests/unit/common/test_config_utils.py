from __future__ import annotations

from quickquip.common.config_utils import as_bool, as_dict, expand_env_value


def test_expand_env_value_handles_nested_defaults(monkeypatch):
    monkeypatch.setenv("QQ_SAMPLE_PATH", "/tmp/qq")

    value = {
        "path": "${QQ_SAMPLE_PATH:-/fallback}",
        "items": ["${QQ_MISSING:-one}", {"inner": "${QQ_MISSING:-two}"}],
    }

    assert expand_env_value(value) == {
        "path": "/tmp/qq",
        "items": ["one", {"inner": "two"}],
    }


def test_as_bool_handles_strings_and_defaults():
    assert as_bool(True) is True
    assert as_bool("yes") is True
    assert as_bool("off") is False
    assert as_bool("maybe", default=True) is True


def test_as_dict_falls_back_to_empty_dict():
    assert as_dict({"x": 1}) == {"x": 1}
    assert as_dict(None) == {}
