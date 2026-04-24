from __future__ import annotations

import asyncio

from quickquip.generation.audio import generate_audio
from quickquip.generation.config import AudioModelConfig, AudioProviderConfig


def test_generate_audio_minimax_http_hex(monkeypatch):
    async def fake_http_json(url, *, method, headers, payload, timeout):
        assert url == "https://example.test/v1/t2a_v2"
        assert method == "POST"
        assert payload["voice_setting"]["voice_id"] == "male-qn-qingse"
        assert payload["audio_setting"]["format"] == "mp3"
        return {
            "base_resp": {"status_code": 0},
            "data": {
                "audio": "68656c6c6f",
                "subtitle": "hello",
                "extra_info": {"audio_length": 1234},
            },
        }

    monkeypatch.setattr("quickquip.generation.audio._http_json", fake_http_json)
    monkeypatch.setattr("quickquip.generation.audio._get_api_key", lambda provider: "secret")

    provider = AudioProviderConfig(
        id="minimax-audio",
        protocol="minimax_t2a_http",
        base_url="https://example.test/v1",
        api_key_env="MINIMAX_API_KEY",
    )
    model = AudioModelConfig(
        id="minimax-speech",
        model="speech-2.8-hd",
        voice_id="male-qn-qingse",
        format="mp3",
    )

    result = asyncio.run(generate_audio(model, provider, "你好"))

    assert result.audio_bytes == b"hello"
    assert result.mime_type == "audio/mpeg"
    assert result.subtitle == "hello"
    assert result.extra_info == {"audio_length": 1234}

