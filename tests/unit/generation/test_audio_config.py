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


def test_load_asr_config_from_generation_file(tmp_path: Path):
    config_path = tmp_path / "generation.toml"
    config_path.write_text(
        textwrap.dedent(
            """
            [asr]
            enabled = true
            default_model = "whisper"
            max_audio_bytes = 12345

            [[asr.providers]]
            id = "openai-asr"
            protocol = "openai_transcriptions"
            base_url = "https://example.test/v1"
            api_key_env = "OPENAI_API_KEY"

            [[asr.providers.models]]
            id = "whisper"
            model = "whisper-1"
            language = "zh"
            prompt = "群聊语音"
            response_format = "json"
            """
        ).strip(),
        encoding="utf-8",
    )

    loaded = load_generation_config(config_path)

    assert loaded.load_error is None
    assert loaded.asr.enabled is True
    assert loaded.asr.max_audio_bytes == 12345
    resolved = loaded.asr.resolve_model()
    assert resolved is not None
    assert resolved.provider.id == "openai-asr"
    assert resolved.model_config.language == "zh"
    assert resolved.model_config.prompt == "群聊语音"


def test_load_audio_openai_tts_no_api_key(tmp_path: Path):
    """openai_tts 本地协议无 api_key_env 时校验应通过（本地服务常无鉴权）。"""
    config_path = tmp_path / "generation.toml"
    config_path.write_text(
        textwrap.dedent(
            """
            [audio]
            enabled = true
            default_model = "local-tts"

            [[audio.providers]]
            id = "local-openai-tts"
            protocol = "openai_tts"
            base_url = "http://127.0.0.1:8000/v1"

            [[audio.providers.models]]
            id = "local-tts"
            model = "tts-1"
            voice_id = "alloy"
            format = "mp3"
            """
        ).strip(),
        encoding="utf-8",
    )

    loaded = load_generation_config(config_path)

    assert loaded.load_error is None
    resolved = loaded.audio.resolve_model()
    assert resolved is not None
    assert resolved.provider.protocol == "openai_tts"
    assert resolved.provider.api_key_env == ""


def test_load_audio_http_tts_no_api_key(tmp_path: Path):
    """http_tts 本地协议无 api_key_env 时校验应通过。"""
    config_path = tmp_path / "generation.toml"
    config_path.write_text(
        textwrap.dedent(
            """
            [audio]
            enabled = true
            default_model = "piper-tts"

            [[audio.providers]]
            id = "local-http-tts"
            protocol = "http_tts"
            base_url = "http://127.0.0.1:5000"

            [[audio.providers.models]]
            id = "piper-tts"
            model = "zh_CN-huayan-medium"
            voice_id = "huayan"
            format = "wav"

            [audio.providers.models.extra_body]
            __path = "/synthesize"
            text = "{text}"
            voice = "{voice}"
            """
        ).strip(),
        encoding="utf-8",
    )

    loaded = load_generation_config(config_path)

    assert loaded.load_error is None
    resolved = loaded.audio.resolve_model()
    assert resolved is not None
    assert resolved.provider.protocol == "http_tts"


def test_load_audio_unknown_protocol_still_rejected(tmp_path: Path):
    """非白名单协议仍应被拒绝（防止校验放宽误伤）。"""
    config_path = tmp_path / "generation.toml"
    config_path.write_text(
        textwrap.dedent(
            """
            [audio]
            enabled = true
            default_model = "m"

            [[audio.providers]]
            id = "bad"
            protocol = "some_unknown_protocol"
            base_url = "https://example.test/v1"
            api_key_env = "X"

            [[audio.providers.models]]
            id = "m"
            model = "m"
            """
        ).strip(),
        encoding="utf-8",
    )

    loaded = load_generation_config(config_path)

    assert loaded.load_error is not None
    assert "未知协议" in loaded.load_error
