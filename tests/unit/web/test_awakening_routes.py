from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
HTTPException = fastapi.HTTPException

from quickquip.app.web.routes import awakening as awakening_route  # noqa: E402
from quickquip.chat import awakening as awakening_config  # noqa: E402


@pytest.fixture()
def temp_awakening_config(monkeypatch, tmp_path):
    path = tmp_path / "awakening.toml"
    monkeypatch.setattr(awakening_route, "_CONFIG_PATH", path)
    awakening_config.reload_config(path)
    try:
        yield path
    finally:
        awakening_config.reload_config()


def _write_config(path, content: str) -> None:
    path.write_text(content.strip() + "\n", encoding="utf-8")
    awakening_config.reload_config(path)


def test_apply_group_settings_preserves_interest_topics(temp_awakening_config):
    _write_config(
        temp_awakening_config,
        """
        [awakening.defaults]
        fallback_probability = 0.01

        [[awakening.group_overrides]]
        group_id = "123456"
        interest_topics = ["Python", "LLM"]
        fallback_probability = 0.2
        """,
    )

    _before, after = awakening_route._apply_group_settings(
        "123456",
        {"fallback_probability": 0.35, "relevance_threshold": 0.6},
    )

    assert after["interest_topics"] == ["Python", "LLM"]
    assert after["fallback_probability"] == 0.35
    assert after["relevance_threshold"] == 0.6

    saved = awakening_config.load_awakening_config(temp_awakening_config)
    override = saved.group_overrides["123456"]
    assert override.interest_topics == ["Python", "LLM"]
    assert override.fallback_probability == 0.35
    assert override.relevance_threshold == 0.6


def test_clearing_editable_fields_keeps_interest_only_override(temp_awakening_config):
    _write_config(
        temp_awakening_config,
        """
        [awakening.defaults]
        fallback_probability = 0.01

        [[awakening.group_overrides]]
        group_id = "123456"
        interest_topics = ["Python"]
        fallback_probability = 0.2
        """,
    )

    _before, after = awakening_route._apply_group_settings("123456", {"fallback_probability": None})

    assert after["interest_topics"] == ["Python"]
    assert after["fallback_probability"] is None

    saved = awakening_config.load_awakening_config(temp_awakening_config)
    assert "123456" in saved.group_overrides
    assert saved.group_overrides["123456"].interest_topics == ["Python"]
    assert saved.group_overrides["123456"].fallback_probability is None


def test_validate_settings_payload_rejects_bool_numbers():
    with pytest.raises(HTTPException) as int_exc:
        awakening_route._validate_settings_payload({"extend_duration": True})
    assert int_exc.value.status_code == 422

    with pytest.raises(HTTPException) as float_exc:
        awakening_route._validate_settings_payload({"fallback_probability": False})
    assert float_exc.value.status_code == 422
