from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
HTTPException = fastapi.HTTPException

from quickquip.app.web.routes import awakening as awakening_route  # noqa: E402
from quickquip.chat import awakening as awakening_config  # noqa: E402


@pytest.fixture()
def temp_awakening_config(monkeypatch, tmp_path):
    path = tmp_path / "awakening.toml"
    boredom_path = tmp_path / "awakening_boredom_groups.json"
    monkeypatch.setattr(awakening_route, "_CONFIG_PATH", path)
    monkeypatch.setattr(awakening_route, "_BOREDOM_GROUPS_PATH", boredom_path)
    # stats_tracker 现在在 handler 内懒导入，mock 其真实来源 message_pipeline
    from quickquip.app.message_pipeline import stats_tracker

    monkeypatch.setattr(stats_tracker, "to_dict", lambda: {})
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


def test_list_awakening_does_not_expose_source_path(temp_awakening_config):
    result = awakening_route.list_awakening()

    assert "source_path" not in result


def test_list_awakening_exposes_effective_scan_interval(temp_awakening_config):
    _write_config(
        temp_awakening_config,
        """
        [awakening.defaults]
        boredom_check_interval = 600
        """,
    )
    result = awakening_route.list_awakening()
    assert result["defaults"]["boredom_scan_interval"] is None
    assert result["effective_boredom_scan_interval"] == 600


def test_render_keeps_scan_interval_fallback_dynamic(temp_awakening_config):
    """Web Admin 保存不把回退值物化进托管文件：未设置即不写键。"""
    _write_config(
        temp_awakening_config,
        """
        [awakening.defaults]
        boredom_check_interval = 600
        """,
    )
    cfg = awakening_route.get_config()
    content = awakening_route._render_awakening_config(cfg)
    assert "boredom_scan_interval" not in content

    import tomllib

    parsed = tomllib.loads(content)
    assert parsed["awakening"]["defaults"]["boredom_check_interval"] == 600


def test_set_awakening_settings_queues_awakening_reload(monkeypatch, temp_awakening_config):
    captured: list[str] = []
    monkeypatch.setattr(awakening_route.action_queue, "enqueue", lambda action_type: captured.append(action_type) or {"id": "a1"})
    monkeypatch.setattr(awakening_route.audit_logger, "log", lambda *args, **kwargs: None)

    result = awakening_route.set_awakening_settings(
        "123456",
        awakening_route.AwakeningSettingsBody(fallback_probability=0.25),
        object(),
    )

    assert result["ok"] is True
    assert captured == ["awakening_reload"]


def test_validate_settings_payload_rejects_bool_numbers():
    with pytest.raises(HTTPException) as int_exc:
        awakening_route._validate_settings_payload({"extend_duration": True})
    assert int_exc.value.status_code == 422

    with pytest.raises(HTTPException) as float_exc:
        awakening_route._validate_settings_payload({"fallback_probability": False})
    assert float_exc.value.status_code == 422
