from __future__ import annotations

import textwrap
from pathlib import Path

from quickquip.generation.config import load_generation_config


def test_svg_section_defaults_when_absent(tmp_path: Path):
    config_path = tmp_path / "generation.toml"
    config_path.write_text("[image]\nenabled = false\n", encoding="utf-8")

    loaded = load_generation_config(config_path)

    assert loaded.svg.enabled is False
    assert loaded.svg.harden is True
    assert loaded.svg.content_judge is False


def test_svg_section_reads_toggles(tmp_path: Path):
    config_path = tmp_path / "generation.toml"
    config_path.write_text(
        textwrap.dedent(
            """
            [svg]
            enabled = true
            harden = false
            content_judge = true
            """
        ).strip(),
        encoding="utf-8",
    )

    loaded = load_generation_config(config_path)

    assert loaded.svg.enabled is True
    assert loaded.svg.harden is False
    assert loaded.svg.content_judge is True


def test_svg_section_supports_env_expansion(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "generation.toml"
    config_path.write_text(
        '[svg]\nenabled = "${SVG_ON:-true}"\n', encoding="utf-8"
    )
    monkeypatch.setenv("SVG_ON", "true")

    loaded = load_generation_config(config_path)

    assert loaded.svg.enabled is True
