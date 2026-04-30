from __future__ import annotations

from pathlib import Path

import pytest

from quickquip.adapters.nonebot.voice import (
    append_voice_transcripts,
    extract_embedded_voice_transcripts,
    transcribe_message_records,
)
from quickquip.generation.config import load_generation_config
from quickquip.generation.service import generation_service
from quickquip.generation.asr import TranscriptionResult
from tests.fixtures.onebot import DummyMessage, record_seg, text_seg


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
    config_path.write_text(
        """
        [asr]
        enabled = true
        default_model = "whisper"

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
    audio_file = tmp_path / "voice.wav"
    audio_file.write_bytes(b"audio")

    class DummyBot:
        async def get_record(self, *, file, out_format):
            assert file == "abc.silk"
            assert out_format == "wav"
            return {"file": str(audio_file)}

    original_config_path = generation_service.config_path
    original_legacy_path = generation_service.legacy_llm_path
    original_config = generation_service._config
    original_active_mtime = generation_service._active_mtime
    original_legacy_mtime = generation_service._legacy_mtime

    async def fake_transcribe(model_config, provider, audio_bytes, *, filename, mime_type):
        assert model_config.model == "whisper-1"
        assert provider.id == "openai-asr"
        assert audio_bytes == b"audio"
        assert filename == "voice.wav"
        assert mime_type == "audio/wav"
        return TranscriptionResult(text="转写结果")

    try:
        generation_service.config_path = config_path
        generation_service.legacy_llm_path = tmp_path / "missing-llm.toml"
        generation_service.reload()
        monkeypatch.setattr("quickquip.adapters.nonebot.voice.transcribe_audio", fake_transcribe)

        transcripts = await transcribe_message_records(
            DummyBot(),
            DummyMessage([text_seg("/ai"), record_seg("abc.silk")]),
        )

        assert [item.text for item in transcripts] == ["转写结果"]
    finally:
        generation_service.config_path = original_config_path
        generation_service.legacy_llm_path = original_legacy_path
        generation_service._config = original_config
        generation_service._active_mtime = original_active_mtime
        generation_service._legacy_mtime = original_legacy_mtime


def test_asr_config_can_be_reloaded_after_voice_test_cleanup(tmp_path: Path):
    missing = tmp_path / "missing.toml"
    loaded = load_generation_config(missing, legacy_llm_path=missing)
    assert loaded.load_error
