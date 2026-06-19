from __future__ import annotations

import asyncio

from quickquip.generation.audio import generate_audio
from quickquip.generation.config import AudioModelConfig, AudioProviderConfig


def test_generate_audio_openai_tts(monkeypatch):
    async def fake_http_raw_bytes(url, *, headers, payload, timeout):
        assert url == "http://127.0.0.1:8000/v1/audio/speech"
        assert payload["model"] == "tts-1"
        assert payload["input"] == "你好"
        assert payload["voice"] == "alloy"
        assert payload["response_format"] == "mp3"
        # 本地无鉴权时不应带 Authorization
        assert "Authorization" not in headers
        return b"FAKE-AUDIO-BYTES", "audio/mpeg"

    monkeypatch.setattr("quickquip.generation.audio._http_raw_bytes", fake_http_raw_bytes)

    provider = AudioProviderConfig(
        id="local-openai-tts",
        protocol="openai_tts",
        base_url="http://127.0.0.1:8000/v1",
        api_key_env="",  # 本地无鉴权
        timeout_seconds=60.0,
    )
    model = AudioModelConfig(
        id="local-tts",
        model="tts-1",
        voice_id="alloy",
        format="mp3",
    )

    result = asyncio.run(generate_audio(model, provider, "你好"))

    assert result.audio_bytes == b"FAKE-AUDIO-BYTES"
    assert result.mime_type == "audio/mpeg"
    assert result.format == "mp3"


def test_generate_audio_openai_tts_with_voice_override(monkeypatch):
    """--voice 参数应覆盖 model_config.voice_id。"""
    captured: dict = {}

    async def fake_http_raw_bytes(url, *, headers, payload, timeout):
        captured["voice"] = payload["voice"]
        return b"BYTES", "audio/mpeg"

    monkeypatch.setattr("quickquip.generation.audio._http_raw_bytes", fake_http_raw_bytes)

    provider = AudioProviderConfig(
        id="local-openai-tts",
        protocol="openai_tts",
        base_url="http://127.0.0.1:8000/v1",
        api_key_env="",
    )
    model = AudioModelConfig(id="local-tts", model="tts-1", voice_id="alloy", format="mp3")

    asyncio.run(generate_audio(model, provider, "测试文本", voice_id="nova"))

    assert captured["voice"] == "nova"


def test_generate_audio_openai_tts_with_api_key(monkeypatch):
    """配置了 api_key_env 时应附加 Bearer 鉴权头。"""
    monkeypatch.setenv("LOCAL_TTS_KEY", "secret-key-123")

    headers_seen: dict = {}

    async def fake_http_raw_bytes(url, *, headers, payload, timeout):
        headers_seen.update(headers)
        return b"BYTES", "audio/mpeg"

    monkeypatch.setattr("quickquip.generation.audio._http_raw_bytes", fake_http_raw_bytes)

    provider = AudioProviderConfig(
        id="local-openai-tts",
        protocol="openai_tts",
        base_url="http://127.0.0.1:8000/v1",
        api_key_env="LOCAL_TTS_KEY",
    )
    model = AudioModelConfig(id="local-tts", model="tts-1", voice_id="alloy", format="mp3")

    asyncio.run(generate_audio(model, provider, "鉴权测试"))

    assert headers_seen["Authorization"] == "Bearer secret-key-123"


def test_generate_audio_openai_tts_empty_response(monkeypatch):
    async def fake_http_raw_bytes(url, *, headers, payload, timeout):
        return b"", "audio/mpeg"

    monkeypatch.setattr("quickquip.generation.audio._http_raw_bytes", fake_http_raw_bytes)

    provider = AudioProviderConfig(
        id="local-openai-tts", protocol="openai_tts", base_url="http://127.0.0.1:8000/v1", api_key_env=""
    )
    model = AudioModelConfig(id="local-tts", model="tts-1", voice_id="alloy", format="mp3")

    try:
        asyncio.run(generate_audio(model, provider, "测试"))
        assert False, "应抛出空响应错误"
    except Exception as exc:
        assert "空响应" in str(exc)
