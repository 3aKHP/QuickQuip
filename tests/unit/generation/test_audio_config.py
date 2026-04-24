from __future__ import annotations

import textwrap
from pathlib import Path

from quickquip.generation.config import load_generation_config


def test_load_audio_generation_from_generation_file(tmp_path: Path):
    config_path = tmp_path / "generation.toml"
    config_path.write_text(
        textwrap.dedent(
            """
            [audio]
            enabled = true
            default_model = "minimax-speech"
            prompt_blocklist = [" banned "]

            [[audio.providers]]
            id = "minimax-audio"
            protocol = "minimax_t2a_http"
            base_url = "https://example.test/v1"
            api_key_env = "MINIMAX_API_KEY"

            [[audio.providers.models]]
            id = "minimax-speech"
            model = "speech-2.8-hd"
            voice_id = "male-qn-qingse"
            format = "mp3"
            sample_rate = 32000
            bitrate = 128000
            channel = 1
            speed = 1.1
            vol = 0.9
            pitch = 1
            subtitle_enable = true
            output_format = "hex"
            """
        ).strip(),
        encoding="utf-8",
    )

    loaded = load_generation_config(config_path)

    assert loaded.load_error is None
    assert loaded.audio.enabled is True
    assert loaded.audio.prompt_blocklist == ["banned"]
    resolved = loaded.audio.resolve_model()
    assert resolved is not None
    assert resolved.provider.id == "minimax-audio"
    assert resolved.model_config.voice_id == "male-qn-qingse"
    assert resolved.model_config.subtitle_enable is True

