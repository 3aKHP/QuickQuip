from __future__ import annotations

import io
import math
from pathlib import Path
import struct
import wave

import pilk_nogil
import pytest

from quickquip.adapters.nonebot.voice import (
    append_voice_transcripts,
    extract_embedded_voice_transcripts,
    transcribe_message_records,
)
from quickquip.generation.asr import TranscriptionResult
from quickquip.generation.audio_transcode import validate_wav_bytes
from quickquip.generation.service import generation_service
from tests.fixtures.onebot import DummyMessage, record_seg, text_seg


def _make_sine_pcm(sample_rate: int = 24000, duration_s: float = 0.2, freq: float = 440.0) -> bytes:
    count = int(sample_rate * duration_s)
    samples = [int(12000 * math.sin(2.0 * math.pi * freq * i / sample_rate)) for i in range(count)]
    return struct.pack(f"<{count}h", *samples)


def _make_wav_bytes(sample_rate: int = 16000, duration_s: float = 0.1) -> bytes:
    pcm = _make_sine_pcm(sample_rate=sample_rate, duration_s=duration_s)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)
    return buf.getvalue()


def _make_silk_bytes(*, tencent: bool, duration_s: float = 0.2) -> bytes:
    pcm = _make_sine_pcm(sample_rate=24000, duration_s=duration_s)
    return pilk_nogil.encode(pcm, None, pcm_rate=24000, tencent=tencent)


def _write_asr_config(config_path: Path, *, extra_asr_toml: str = "") -> None:
    config_path.write_text(
        f"""
        [asr]
        enabled = true
        default_model = "whisper"
        {extra_asr_toml}

        [[asr.providers]]
        id = "openai-asr"
        protocol = "openai_transcriptions"
        base_url = "https://example.test/v1"
        api_key_env = "OPENAI_API_KEY"

        [[asr.providers.models]]
        id = "whisper"
        model = "whisper-1"
        """,
        encoding="utf-8",
    )


class _DummyHttpResponse:
    def __init__(self, body: bytes, content_type: str = "application/octet-stream"):
        self._stream = io.BytesIO(body)
        self.headers = _DummyHeaders(
            {"Content-Length": str(len(body)), "Content-Type": content_type}
        )

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummyHeaders(dict):
    def get_content_type(self) -> str:
        return self.get("Content-Type", "application/octet-stream")


def _swap_generation_config(config_path: Path):
    original_config_path = generation_service.config_path
    original_config = generation_service._config
    original_active_mtime = generation_service._active_mtime
    generation_service.config_path = config_path
    generation_service.reload()

    def _restore() -> None:
        generation_service.config_path = original_config_path
        generation_service._config = original_config
        generation_service._active_mtime = original_active_mtime

    return _restore


def test_extract_embedded_voice_transcript():
    message = DummyMessage([record_seg("abc.silk", text="你好")])

    transcripts = extract_embedded_voice_transcripts(message)

    assert len(transcripts) == 1
    assert transcripts[0].text == "你好"
    assert transcripts[0].source == "segment"
    assert append_voice_transcripts("讲讲这个", transcripts) == "讲讲这个\n[语音转文字：你好]"


@pytest.mark.asyncio
async def test_transcribe_message_records_uses_get_record_and_asr(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "generation.toml"
    _write_asr_config(config_path)
    wav_bytes = _make_wav_bytes()
    audio_file = tmp_path / "voice.wav"
    audio_file.write_bytes(wav_bytes)

    class DummyBot:
        async def get_record(self, *, file, out_format):
            assert file == "abc.silk"
            assert out_format == "wav"
            return {"file": str(audio_file)}

    async def fake_transcribe(model_config, provider, audio_bytes, *, filename, mime_type):
        assert model_config.model == "whisper-1"
        assert provider.id == "openai-asr"
        assert audio_bytes == wav_bytes
        assert filename == "voice.wav"
        assert mime_type == "audio/wav"
        return TranscriptionResult(text="转写结果")

    restore = _swap_generation_config(config_path)
    try:
        monkeypatch.setattr("quickquip.adapters.nonebot.voice.transcribe_audio", fake_transcribe)

        transcripts = await transcribe_message_records(
            DummyBot(),
            DummyMessage([text_seg("/ai"), record_seg("abc.silk")]),
        )

        assert [item.text for item in transcripts] == ["转写结果"]
    finally:
        restore()


@pytest.mark.asyncio
async def test_transcribe_url_raw_silk_transcodes_to_wav(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "generation.toml"
    _write_asr_config(config_path)
    silk_bytes = _make_silk_bytes(tencent=True, duration_s=0.2)
    captured: list[tuple[bytes, str, str]] = []

    def fake_urlopen(req, timeout=30):
        assert req.full_url == "https://media.example.test/download?fileid=123"
        return _DummyHttpResponse(silk_bytes)

    async def fake_transcribe(model_config, provider, audio_bytes, *, filename, mime_type):
        captured.append((audio_bytes, filename, mime_type))
        return TranscriptionResult(text="URL 语音")

    restore = _swap_generation_config(config_path)
    try:
        monkeypatch.setattr("quickquip.adapters.nonebot.voice.request.urlopen", fake_urlopen)
        monkeypatch.setattr("quickquip.adapters.nonebot.voice.transcribe_audio", fake_transcribe)

        transcripts = await transcribe_message_records(
            object(),
            DummyMessage(
                [
                    record_seg(
                        "raw.amr",
                        url="https://media.example.test/download?fileid=123",
                    )
                ]
            ),
        )

        assert [item.text for item in transcripts] == ["URL 语音"]
        assert len(captured) == 1
        wav_bytes, filename, mime_type = captured[0]
        assert filename == "download.wav"
        assert mime_type == "audio/wav"
        assert validate_wav_bytes(wav_bytes, expected_sample_rate=16000) == (1, 2, 16000, 3200)
    finally:
        restore()


@pytest.mark.asyncio
async def test_transcribe_existing_local_raw_silk_transcodes_without_get_record(
    tmp_path: Path,
    monkeypatch,
):
    config_path = tmp_path / "generation.toml"
    _write_asr_config(config_path)
    local_silk = tmp_path / "cached_voice.amr"
    local_silk.write_bytes(_make_silk_bytes(tencent=False, duration_s=0.2))
    captured: list[tuple[bytes, str, str]] = []

    class ForbidGetRecordBot:
        async def get_record(self, **kwargs):
            raise AssertionError("本地已存在文件不应再调用 get_record")

    async def fake_transcribe(model_config, provider, audio_bytes, *, filename, mime_type):
        captured.append((audio_bytes, filename, mime_type))
        return TranscriptionResult(text="本地原始语音")

    restore = _swap_generation_config(config_path)
    try:
        monkeypatch.setattr("quickquip.adapters.nonebot.voice.transcribe_audio", fake_transcribe)

        transcripts = await transcribe_message_records(
            ForbidGetRecordBot(),
            DummyMessage([record_seg(str(local_silk))]),
        )

        assert [item.text for item in transcripts] == ["本地原始语音"]
        assert len(captured) == 1
        wav_bytes, filename, mime_type = captured[0]
        assert filename == "cached_voice.wav"
        assert mime_type == "audio/wav"
        assert validate_wav_bytes(wav_bytes, expected_sample_rate=16000) == (1, 2, 16000, 3200)
    finally:
        restore()


@pytest.mark.asyncio
async def test_transcribe_multi_segment_skips_invalid_and_keeps_valid(
    tmp_path: Path,
    monkeypatch,
):
    config_path = tmp_path / "generation.toml"
    _write_asr_config(config_path)

    payloads = {
        "https://media.example.test/seg1": _make_silk_bytes(tencent=True, duration_s=0.16),
        "https://media.example.test/seg2": b"\x02#!SILK_V3\x10\x00\xaa",  # 截断损坏
        "https://media.example.test/seg3": b"<html>expired link</html>",  # 非音频
        "https://media.example.test/seg4": _make_wav_bytes(duration_s=0.1),
    }

    def fake_urlopen(req, timeout=30):
        return _DummyHttpResponse(payloads[req.full_url])

    calls: list[str] = []

    async def fake_transcribe(model_config, provider, audio_bytes, *, filename, mime_type):
        calls.append(filename)
        assert mime_type == "audio/wav"
        return TranscriptionResult(text=f"结果-{len(calls)}")

    restore = _swap_generation_config(config_path)
    try:
        monkeypatch.setattr("quickquip.adapters.nonebot.voice.request.urlopen", fake_urlopen)
        monkeypatch.setattr("quickquip.adapters.nonebot.voice.transcribe_audio", fake_transcribe)

        transcripts = await transcribe_message_records(
            object(),
            DummyMessage(
                [
                    record_seg("1.amr", url="https://media.example.test/seg1"),
                    record_seg("2.amr", url="https://media.example.test/seg2"),
                    record_seg("3.amr", url="https://media.example.test/seg3"),
                    record_seg("4.wav", url="https://media.example.test/seg4"),
                ]
            ),
        )

        assert [item.text for item in transcripts] == ["结果-1", "结果-2"]
        assert calls == ["seg1.wav", "seg4.wav"]
        assert append_voice_transcripts("", transcripts) == (
            "[语音1转文字：结果-1]\n[语音2转文字：结果-2]"
        )
    finally:
        restore()


@pytest.mark.asyncio
async def test_transcribe_respects_max_decoded_bytes_config(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "generation.toml"
    # 0.2s @ 16kHz WAV = 6444 bytes；配置 2000 bytes 应跳过
    _write_asr_config(config_path, extra_asr_toml="max_decoded_bytes = 2000")
    local_silk = tmp_path / "voice.silk"
    local_silk.write_bytes(_make_silk_bytes(tencent=True, duration_s=0.2))

    async def forbid_transcribe(*args, **kwargs):
        raise AssertionError("超限解码音频不应发送给 ASR")

    restore = _swap_generation_config(config_path)
    try:
        monkeypatch.setattr("quickquip.adapters.nonebot.voice.transcribe_audio", forbid_transcribe)

        transcripts = await transcribe_message_records(
            object(),
            DummyMessage([record_seg(str(local_silk))]),
        )

        assert transcripts == []
    finally:
        restore()
