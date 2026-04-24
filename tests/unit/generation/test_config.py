from __future__ import annotations

import textwrap
from pathlib import Path

from quickquip.generation.config import load_generation_config
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


def test_load_generation_config_falls_back_to_legacy_llm_file(tmp_path: Path):
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

    loaded = load_generation_config(
        tmp_path / "generation.toml",
        legacy_llm_path=legacy_path,
    )

    assert loaded.load_error is None
    assert loaded.source_kind == "llm_legacy"
    assert loaded.source_path == legacy_path
    assert loaded.image.enabled is True
    assert loaded.image.default_model == "minimax-image"
    assert loaded.image.resolve_model("minimax-image") is not None


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

    service = GenerationService(generation_path, legacy_llm_path=legacy_path)
    resolved = service.resolve_image_model()

    assert resolved is not None
    assert resolved.id == "new-image"
    assert resolved.provider.id == "new-provider"
