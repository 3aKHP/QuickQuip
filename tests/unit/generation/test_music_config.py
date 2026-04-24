from __future__ import annotations

import textwrap
from pathlib import Path

from quickquip.generation.config import load_generation_config


def test_load_music_generation_from_generation_file(tmp_path: Path):
    config_path = tmp_path / "generation.toml"
    config_path.write_text(
        textwrap.dedent(
            """
            [music]
            enabled = true
            default_model = "minimax-music"
            prompt_blocklist = [" banned "]

            [[music.providers]]
            id = "minimax-music-provider"
            protocol = "minimax_music"
            base_url = "https://example.test/v1"
            api_key_env = "MINIMAX_API_KEY"

            [[music.providers.models]]
            id = "minimax-music"
            model = "music-2.6"
            label = "MiniMax Music 2.6"
            sample_rate = 44100
            bitrate = 256000
            format = "mp3"
            output_format = "hex"
            lyrics_optimizer = true
            """
        ).strip(),
        encoding="utf-8",
    )

    loaded = load_generation_config(config_path)

    assert loaded.load_error is None
    assert loaded.music.enabled is True
    assert loaded.music.prompt_blocklist == ["banned"]
    resolved = loaded.music.resolve_model()
    assert resolved is not None
    assert resolved.provider.id == "minimax-music-provider"
    assert resolved.model_config.model == "music-2.6"
    assert resolved.model_config.lyrics_optimizer is True
