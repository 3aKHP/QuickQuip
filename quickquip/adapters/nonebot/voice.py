from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
from urllib import error, request

from quickquip.generation.asr import transcribe_audio
from quickquip.generation.errors import GenerationProviderError
from quickquip.generation.service import generation_service

logger = logging.getLogger(__name__)

@dataclass(slots=True)
class VoiceTranscription:
    text: str
    source: str = "asr"


def _iter_record_segments(message):
    for segment in list(message):
        segment_type = getattr(segment, "type", None)
        data = getattr(segment, "data", None)
        if segment_type is None and isinstance(segment, dict):
            segment_type = segment.get("type", "")
        if data is None and isinstance(segment, dict):
            data = segment.get("data", {})
        if str(segment_type or "") == "record":
            yield data or {}


def has_record_segment(message) -> bool:
    return any(True for _ in _iter_record_segments(message))


def format_voice_transcripts(transcripts: list[VoiceTranscription]) -> str:
    lines = [item.text.strip() for item in transcripts if item.text.strip()]
    if not lines:
        return ""
    if len(lines) == 1:
        return f"[语音转文字：{lines[0]}]"
    return "\n".join(f"[语音{index}转文字：{text}]" for index, text in enumerate(lines, start=1))


def append_voice_transcripts(text: str, transcripts: list[VoiceTranscription]) -> str:
    formatted = format_voice_transcripts(transcripts)
    if not formatted:
        return text.strip()
    base = text.strip()
    return f"{base}\n{formatted}" if base else formatted


def extract_embedded_voice_transcripts(message) -> list[VoiceTranscription]:
    transcripts: list[VoiceTranscription] = []
    for data in _iter_record_segments(message):
        for key in ("text", "transcript", "transcription"):
            text = str(data.get(key, "") or "").strip()
            if text:
                transcripts.append(VoiceTranscription(text=text, source="segment"))
                break
    return transcripts


async def transcribe_message_records(bot, message) -> list[VoiceTranscription]:
    if not has_record_segment(message):
        return []

    embedded = extract_embedded_voice_transcripts(message)
    if embedded:
        return embedded

    config = generation_service.get_config()
    if config.load_error or not config.asr.enabled:
        return []
    resolved = generation_service.resolve_asr_model()
    if resolved is None:
        return []

    transcripts: list[VoiceTranscription] = []
    for data in _iter_record_segments(message):
        file_ref = str(data.get("file", "") or "").strip()
        url = str(data.get("url", "") or "").strip()
        if not file_ref and not url:
            continue
        try:
            audio_bytes, filename, mime_type = await _load_record_audio(
                bot=bot,
                file_ref=file_ref,
                url=url,
                max_audio_bytes=config.asr.max_audio_bytes,
            )
            result = await transcribe_audio(
                resolved.model_config,
                resolved.provider,
                audio_bytes,
                filename=filename,
                mime_type=mime_type,
            )
        except GenerationProviderError:
            logger.info("voice ASR skipped for one record segment", exc_info=True)
            continue
        if result.text:
            transcripts.append(VoiceTranscription(text=result.text, source="asr"))
    return transcripts


async def _load_record_audio(
    *,
    bot,
    file_ref: str,
    url: str,
    max_audio_bytes: int,
) -> tuple[bytes, str, str]:
    if url.startswith(("http://", "https://")):
        return await _download_audio(url, max_audio_bytes=max_audio_bytes)
    if file_ref.startswith(("http://", "https://")):
        return await _download_audio(file_ref, max_audio_bytes=max_audio_bytes)

    local_path = await _resolve_record_path(bot, file_ref)
    filename = Path(local_path).name or "voice.wav"

    def _read() -> bytes:
        data = Path(local_path).read_bytes()
        if len(data) > max_audio_bytes:
            raise GenerationProviderError("语音文件过大，跳过 ASR")
        return data

    audio_bytes = await asyncio.to_thread(_read)
    return audio_bytes, filename, _guess_mime(filename)


async def _resolve_record_path(bot, file_ref: str) -> str:
    if Path(file_ref).exists():
        return file_ref

    result = None
    if hasattr(bot, "get_record"):
        result = await bot.get_record(file=file_ref, out_format="wav")
    elif hasattr(bot, "call_api"):
        result = await bot.call_api("get_record", file=file_ref, out_format="wav")
    if isinstance(result, dict):
        record_file = str(result.get("file", "") or "").strip()
        if record_file:
            return record_file
    raise GenerationProviderError("OneBot get_record 未返回可读取文件")


async def _download_audio(url: str, *, max_audio_bytes: int) -> tuple[bytes, str, str]:
    def _fetch() -> tuple[bytes, str, str]:
        try:
            req = request.Request(url, headers={"User-Agent": "QuickQuip/1.0"})
            with request.urlopen(req, timeout=30) as resp:
                content_length = resp.headers.get("Content-Length")
                if content_length and int(content_length) > max_audio_bytes:
                    raise GenerationProviderError("语音文件过大，跳过 ASR")
                data = resp.read(max_audio_bytes + 1)
                if len(data) > max_audio_bytes:
                    raise GenerationProviderError("语音文件过大，跳过 ASR")
                mime_type = resp.headers.get_content_type() or "application/octet-stream"
        except error.HTTPError as exc:
            raise GenerationProviderError(f"语音下载失败：HTTP {exc.code}") from exc
        except error.URLError as exc:
            raise GenerationProviderError(f"语音下载失败：{exc.reason}") from exc
        except OSError as exc:
            raise GenerationProviderError(f"语音下载失败：{exc}") from exc
        filename = Path(url.split("?", 1)[0]).name or "voice"
        return data, filename, mime_type

    return await asyncio.to_thread(_fetch)


def _guess_mime(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".amr":
        return "audio/amr"
    if suffix == ".silk":
        return "audio/silk"
    return "application/octet-stream"
