from quickquip.app.web.routes import sensitive_filter


def test_sensitive_filter_status_does_not_expose_path(monkeypatch, tmp_path):
    path = tmp_path / "sensitive_words.toml"
    path.write_text(
        """
[block]
words = ["secret"]

[soft]
words = ["watch"]
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(sensitive_filter, "CONFIG_SENSITIVE_WORDS_TOML", path)

    result = sensitive_filter.get_sensitive_filter_status()

    assert result["loaded"] is True
    assert result["config_exists"] is True
    assert result["stats"] == {"total": 2, "block": 1, "soft": 1}
    assert "config_path" not in result
