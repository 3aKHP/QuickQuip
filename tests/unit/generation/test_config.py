from __future__ import annotations

import textwrap
from pathlib import Path

from quickquip.generation.config import (
    _read_generation_section,
    _select_generation_section,
    generation_environment_sections,
    load_generation_config,
)
from quickquip.generation.service import GenerationService


def test_load_generation_config_from_dedicated_file(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "generation.toml"
    config_path.write_text(
        textwrap.dedent(
            """
            [image]
            enabled = "${QQ_IMAGE_ENABLED:-true}"
            default_model = "seedream4"
            prompt_blocklist = ["Naked", " gore "]

            [[image.providers]]
            id = "volcengine"
            protocol = "openai_images"
            base_url = "https://example.test/v1"
            api_key_env = "VOLCENGINE_API_KEY"

            [[image.providers.models]]
            id = "seedream4"
            model = "doubao-seedream-4-0"
            label = "Seedream 4"
            size = "1024x1024"
            """
        ).strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("QQ_IMAGE_ENABLED", "true")

    loaded = load_generation_config(config_path)

    assert loaded.load_error is None
    assert loaded.source_kind == "generation"
    assert loaded.source_path == config_path
    assert loaded.image.enabled is True
    assert loaded.image.prompt_blocklist == ["naked", "gore"]
    resolved = loaded.image.resolve_model()
    assert resolved is not None
    assert resolved.id == "seedream4"
    assert resolved.provider.id == "volcengine"
    assert resolved.model_config.model == "doubao-seedream-4-0"


def test_missing_generation_file_does_not_load_legacy_llm_file(tmp_path: Path):
    legacy_path = tmp_path / "llm.toml"
    legacy_path.write_text(
        textwrap.dedent(
            """
            [image_generation]
            enabled = true
            default_model = "minimax-image"

            [[image_generation.providers]]
            id = "minimax"
            protocol = "minimax_images"
            base_url = "https://example.test/v1"
            api_key_env = "MINIMAX_API_KEY"

            [[image_generation.providers.models]]
            id = "minimax-image"
            model = "image-01"
            size = "1:1"
            """
        ).strip(),
        encoding="utf-8",
    )

    loaded = load_generation_config(tmp_path / "generation.toml")
    assert loaded.load_error is not None
    assert loaded.source_kind == "generation"
    assert loaded.image.enabled is False
    assert loaded.image.resolve_model("minimax-image") is None


def test_generation_service_prefers_dedicated_config_over_legacy(tmp_path: Path):
    generation_path = tmp_path / "generation.toml"
    legacy_path = tmp_path / "llm.toml"
    generation_path.write_text(
        textwrap.dedent(
            """
            [image]
            enabled = true
            default_model = "new-image"

            [[image.providers]]
            id = "new-provider"
            protocol = "openai_images"
            base_url = "https://example.test/v1"
            api_key_env = "NEW_KEY"

            [[image.providers.models]]
            id = "new-image"
            model = "new-model"
            """
        ).strip(),
        encoding="utf-8",
    )
    legacy_path.write_text(
        textwrap.dedent(
            """
            [image_generation]
            enabled = true
            default_model = "legacy-image"

            [[image_generation.providers]]
            id = "legacy-provider"
            protocol = "openai_images"
            base_url = "https://legacy.example.test/v1"
            api_key_env = "LEGACY_KEY"

            [[image_generation.providers.models]]
            id = "legacy-image"
            model = "legacy-model"
            """
        ).strip(),
        encoding="utf-8",
    )

    service = GenerationService(generation_path)
    resolved = service.resolve_image_model()

    assert resolved is not None
    assert resolved.id == "new-image"
    assert resolved.provider.id == "new-provider"


def test_select_generation_section_priority():
    nested = {"source": "nested"}
    top_level = {"source": "top-level"}
    legacy = {"source": "legacy"}
    data = {
        "generation": {"image": nested},
        "image": top_level,
        "image_generation": legacy,
    }

    assert _select_generation_section(data, "image", "image_generation") == (
        nested,
        "generation.image",
    )

    data["generation"]["image"] = {}
    assert _select_generation_section(data, "image", "image_generation") == (
        top_level,
        "image",
    )

    data["image"] = {}
    assert _select_generation_section(data, "image", "image_generation") == (
        legacy,
        "image_generation",
    )


def test_generation_environment_sections_preserves_raw_references(monkeypatch):
    monkeypatch.setenv("QQ_PROJECTED_VALUE", "expanded")
    raw_image = {
        "value": "${QQ_PROJECTED_VALUE}",
        "with_default": "${QQ_PROJECTED_MISSING:-fallback}",
        "providers": [{"api_key": "${QQ_PROJECTED_VALUE}"}],
    }
    raw_audio = {"value": "${QQ_PROJECTED_VALUE}"}
    raw_music = {"value": "${QQ_PROJECTED_VALUE:-false}"}
    raw_asr = {"enabled": True}
    data = {
        "generation": {"image": raw_image},
        "audio": raw_audio,
        "music_generation": raw_music,
        "asr": raw_asr,
    }

    sections = generation_environment_sections(data)

    assert [entry["modality"] for entry in sections] == ["image", "audio", "music", "asr"]
    assert [entry["path"] for entry in sections] == [
        "generation.image",
        "audio",
        "music_generation",
        "asr",
    ]
    raw_sections = [raw_image, raw_audio, raw_music, raw_asr]
    assert all(
        entry["section"] is raw_section
        for entry, raw_section in zip(sections, raw_sections, strict=True)
    )
    assert sections[0]["section"] == {
        "value": "${QQ_PROJECTED_VALUE}",
        "with_default": "${QQ_PROJECTED_MISSING:-fallback}",
        "providers": [{"api_key": "${QQ_PROJECTED_VALUE}"}],
    }


def test_generation_section_expansion_result_is_unchanged(monkeypatch):
    monkeypatch.setenv("QQ_OUTER_VALUE", "${QQ_INNER_VALUE}")
    monkeypatch.setenv("QQ_INNER_VALUE", "expanded")
    monkeypatch.delenv("QQ_MISSING_VALUE", raising=False)
    data = {
        "generation": {
            "image": {
                "value": "${QQ_OUTER_VALUE}",
                "with_default": "${QQ_MISSING_VALUE:-fallback}",
            }
        }
    }

    section = _read_generation_section(data, "image", "image_generation", lambda raw: raw)

    assert section == {"value": "expanded", "with_default": "fallback"}


def test_generation_section_legacy_fallback(monkeypatch):
    monkeypatch.setenv("QQ_LEGACY_VALUE", "expanded")
    data = {"image_generation": {"value": "${QQ_LEGACY_VALUE:-fallback}"}}

    section = _read_generation_section(data, "image", "image_generation", lambda raw: raw)

    assert section == {"value": "expanded"}
