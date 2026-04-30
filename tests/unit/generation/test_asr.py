from __future__ import annotations

import json
from urllib import request

import pytest

from quickquip.generation.asr import transcribe_audio
from quickquip.generation.config import AsrModelConfig, AsrProviderConfig


@pytest.mark.asyncio
async def test_openai_transcriptions_builds_multipart_request(monkeypatch):
    captured = {}

    class DummyResponse:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"text": "你好，世界", "language": "zh"}).encode("utf-8")

    def fake_urlopen(req, timeout, context=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = req.data
        captured["timeout"] = timeout
        captured["context"] = context
        return DummyResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(request, "urlopen", fake_urlopen)

    result = await transcribe_audio(
        AsrModelConfig(
            id="whisper",
            model="whisper-1",
            language="zh",
            prompt="群聊语音",
        ),
        AsrProviderConfig(
            id="openai-asr",
            protocol="openai_transcriptions",
            base_url="https://example.test/v1",
            api_key_env="OPENAI_API_KEY",
            timeout_seconds=12,
        ),
        b"abc",
        filename="voice.wav",
        mime_type="audio/wav",
    )

    assert result.text == "你好，世界"
    assert result.language == "zh"
    assert captured["url"] == "https://example.test/v1/audio/transcriptions"
    assert captured["timeout"] == 12
    assert captured["context"] is not None
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert "multipart/form-data" in captured["headers"]["Content-type"]
    assert b'name="model"' in captured["body"]
    assert b"whisper-1" in captured["body"]
    assert b'name="file"; filename="voice.wav"' in captured["body"]
