from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from quickquip.generation.audio import generate_audio
from quickquip.generation.config import AudioModelConfig, AudioProviderConfig


class _FakeResponse:
    def __init__(self, body: bytes, mime_type: str = "audio/wav"):
        self._body = body
        self.headers = MagicMock()
        self.headers.get_content_type.return_value = mime_type

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_generate_audio_http_tts(monkeypatch):
    """http_tts 应按 extra_body 模板构造请求体，做 {text}/{voice} 占位符替换。"""
    captured: dict = {}

    def fake_urlopen(http_request, *, timeout, context):
        import json as _json

        captured["url"] = http_request.full_url
        captured["method"] = http_request.get_method()
        captured["body"] = _json.loads(http_request.data.decode("utf-8"))
        return _FakeResponse(b"WAV-BYTES", "audio/wav")

    monkeypatch.setattr("quickquip.generation.audio.request.urlopen", fake_urlopen)

    provider = AudioProviderConfig(
        id="local-http-tts",
        protocol="http_tts",
        base_url="http://127.0.0.1:5000",
        api_key_env="",
        timeout_seconds=60.0,
    )
    model = AudioModelConfig(
        id="piper-tts",
        model="zh_CN-huayan-medium",
        voice_id="huayan",
        format="wav",
        extra_body={
            "__path": "/synthesize",
            "__method": "POST",
            "text": "{text}",
            "voice": "{voice}",
            "model_id": "zh_CN-huayan-medium",
        },
    )

    result = asyncio.run(generate_audio(model, provider, "你好世界", voice_id="custom"))

    assert captured["url"] == "http://127.0.0.1:5000/synthesize"
    assert captured["method"] == "POST"
    assert captured["body"]["text"] == "你好世界"
    assert captured["body"]["voice"] == "custom"
    assert captured["body"]["model_id"] == "zh_CN-huayan-medium"
    # 下划线开头的内部控制键不应进入请求体
    assert "__path" not in captured["body"]
    assert "__method" not in captured["body"]

    assert result.audio_bytes == b"WAV-BYTES"
    assert result.mime_type == "audio/wav"
    assert result.format == "wav"


def test_generate_audio_http_tts_default_path_and_method(monkeypatch):
    """未配置 __path / __method 时默认走 POST /tts。"""
    captured: dict = {}

    def fake_urlopen(http_request, *, timeout, context):
        captured["url"] = http_request.full_url
        captured["method"] = http_request.get_method()
        return _FakeResponse(b"BYTES", "audio/mpeg")

    monkeypatch.setattr("quickquip.generation.audio.request.urlopen", fake_urlopen)

    provider = AudioProviderConfig(
        id="local-http-tts", protocol="http_tts", base_url="http://127.0.0.1:5000", api_key_env=""
    )
    # extra_body 不含 __path/__method
    model = AudioModelConfig(
        id="simple-tts", model="m", voice_id="v", format="mp3", extra_body={"text": "{text}"}
    )

    asyncio.run(generate_audio(model, provider, "测试"))

    assert captured["url"] == "http://127.0.0.1:5000/tts"
    assert captured["method"] == "POST"


def test_generate_audio_http_tts_json_mime_fallback(monkeypatch):
    """响应 Content-Type 为 application/json 时，回退用 model format 映射 mime。"""

    def fake_urlopen(http_request, *, timeout, context):
        return _FakeResponse(b"BYTES", "application/json")

    monkeypatch.setattr("quickquip.generation.audio.request.urlopen", fake_urlopen)

    provider = AudioProviderConfig(
        id="local-http-tts", protocol="http_tts", base_url="http://127.0.0.1:5000", api_key_env=""
    )
    model = AudioModelConfig(
        id="t", model="m", voice_id="v", format="mp3", extra_body={"__path": "/x", "text": "{text}"}
    )

    result = asyncio.run(generate_audio(model, provider, "测试"))

    assert result.mime_type == "audio/mpeg"


def test_generate_audio_http_tts_path_leading_slash_guard(monkeypatch):
    """__path 缺少前导斜杠时应自动补全，避免拼出畸形 URL。"""
    captured: dict = {}

    def fake_urlopen(http_request, *, timeout, context):
        captured["url"] = http_request.full_url
        return _FakeResponse(b"BYTES", "audio/mpeg")

    monkeypatch.setattr("quickquip.generation.audio.request.urlopen", fake_urlopen)

    provider = AudioProviderConfig(
        id="local-http-tts", protocol="http_tts", base_url="http://127.0.0.1:5000", api_key_env=""
    )
    model = AudioModelConfig(
        id="t", model="m", voice_id="v", format="mp3", extra_body={"__path": "synthesize", "text": "{text}"}
    )

    asyncio.run(generate_audio(model, provider, "测试"))

    assert captured["url"] == "http://127.0.0.1:5000/synthesize"


def test_generate_audio_http_tts_empty_voice(monkeypatch):
    """voice_id=None 且 model_config.voice_id='' 时，应产生空 voice 且不崩溃。"""
    captured: dict = {}

    def fake_urlopen(http_request, *, timeout, context):
        import json as _json

        captured["body"] = _json.loads(http_request.data.decode("utf-8"))
        return _FakeResponse(b"BYTES", "audio/mpeg")

    monkeypatch.setattr("quickquip.generation.audio.request.urlopen", fake_urlopen)

    provider = AudioProviderConfig(
        id="local-http-tts", protocol="http_tts", base_url="http://127.0.0.1:5000", api_key_env=""
    )
    model = AudioModelConfig(
        id="t", model="m", voice_id="", format="mp3", extra_body={"__path": "/tts", "text": "{text}", "voice": "{voice}"}
    )

    asyncio.run(generate_audio(model, provider, "测试"))

    assert captured["body"]["voice"] == ""


def test_generate_audio_http_tts_provider_extra_body_substitution(monkeypatch):
    """provider.extra_body 的字符串字段也应做 {text}/{voice} 占位符替换。"""
    captured: dict = {}

    def fake_urlopen(http_request, *, timeout, context):
        import json as _json

        captured["body"] = _json.loads(http_request.data.decode("utf-8"))
        return _FakeResponse(b"BYTES", "audio/mpeg")

    monkeypatch.setattr("quickquip.generation.audio.request.urlopen", fake_urlopen)

    provider = AudioProviderConfig(
        id="local-http-tts",
        protocol="http_tts",
        base_url="http://127.0.0.1:5000",
        api_key_env="",
        extra_body={"speaker": "{voice}", "fallback_text": "{text}"},
    )
    model = AudioModelConfig(
        id="t", model="m", voice_id="alloy", format="mp3", extra_body={"__path": "/tts", "text": "{text}"}
    )

    asyncio.run(generate_audio(model, provider, "你好"))

    assert captured["body"]["speaker"] == "alloy"
    assert captured["body"]["fallback_text"] == "你好"


def test_generate_audio_http_tts_placeholder_not_leaked_from_text(monkeypatch):
    """用户文本含 {voice} 字面量时，不应被替换成 voice 值（防顺序替换注入）。"""
    captured: dict = {}

    def fake_urlopen(http_request, *, timeout, context):
        import json as _json

        captured["body"] = _json.loads(http_request.data.decode("utf-8"))
        return _FakeResponse(b"BYTES", "audio/mpeg")

    monkeypatch.setattr("quickquip.generation.audio.request.urlopen", fake_urlopen)

    provider = AudioProviderConfig(
        id="local-http-tts", protocol="http_tts", base_url="http://127.0.0.1:5000", api_key_env=""
    )
    model = AudioModelConfig(
        id="t", model="m", voice_id="alloy", format="mp3", extra_body={"__path": "/tts", "text": "{text}"}
    )

    asyncio.run(generate_audio(model, provider, "say {voice} now"))

    assert captured["body"]["text"] == "say {voice} now"
