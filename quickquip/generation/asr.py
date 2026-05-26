from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import mimetypes
import os
import ssl
import uuid
from urllib import error, request

from quickquip.generation.config import AsrModelConfig, AsrProviderConfig
from quickquip.generation.errors import GenerationProviderError


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    language: str = ""
    duration_seconds: float | None = None
    raw: dict | None = None


def _get_api_key(provider: AsrProviderConfig) -> str:
    api_key = os.getenv(provider.api_key_env, "").strip()
    if not api_key:
        raise GenerationProviderError(
            f"环境变量 {provider.api_key_env} 未设置，provider {provider.id} 无法调用"
        )
    return api_key


def _ssl_context():
    try:
        import certifi
    except ModuleNotFoundError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _guess_mime_type(filename: str) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _build_multipart_form(
    fields: dict[str, str],
    file_field: str,
    filename: str,
    file_bytes: bytes,
    mime_type: str,
) -> tuple[bytes, str]:
    boundary = "----QuickQuipAsr" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{filename}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return b"".join(chunks), boundary


async def transcribe_audio(
    model_config: AsrModelConfig,
    provider: AsrProviderConfig,
    audio_bytes: bytes,
    *,
    filename: str = "voice.wav",
    mime_type: str = "",
) -> TranscriptionResult:
    handler = _ASR_DISPATCH.get(provider.protocol)
    if handler is None:
        raise GenerationProviderError(
            f"未知 ASR 协议：{provider.protocol!r}，支持：{', '.join(sorted(_ASR_DISPATCH))}"
        )
    return await handler(
        provider,
        model_config,
        audio_bytes,
        filename=filename,
        mime_type=mime_type or _guess_mime_type(filename),
    )


async def _openai_transcriptions(
    provider: AsrProviderConfig,
    model_config: AsrModelConfig,
    audio_bytes: bytes,
    *,
    filename: str,
    mime_type: str,
) -> TranscriptionResult:
    url = provider.base_url.rstrip("/") + "/audio/transcriptions"
    fields = {
        "model": model_config.model,
        "response_format": model_config.response_format or "json",
    }
    if model_config.language:
        fields["language"] = model_config.language
    if model_config.prompt:
        fields["prompt"] = model_config.prompt
    for key, value in provider.extra_body.items():
        fields[str(key)] = str(value)
    for key, value in model_config.extra_body.items():
        fields[str(key)] = str(value)

    body, boundary = _build_multipart_form(fields, "file", filename, audio_bytes, mime_type)
    headers = {
        **provider.headers,
        "Authorization": f"Bearer {_get_api_key(provider)}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    if provider.user_agent:
        headers["User-Agent"] = provider.user_agent
    http_request = request.Request(url=url, data=body, headers=headers, method="POST")

    def _send() -> TranscriptionResult:
        try:
            with request.urlopen(
                http_request,
                timeout=provider.timeout_seconds,
                context=_ssl_context(),
            ) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GenerationProviderError(f"ASR HTTP {exc.code} {detail[:240]}") from exc
        except error.URLError as exc:
            raise GenerationProviderError(f"ASR 网络错误：{exc.reason}") from exc
        except OSError as exc:
            raise GenerationProviderError(f"ASR 网络错误：{exc}") from exc

        if fields["response_format"] == "text":
            return TranscriptionResult(text=raw.strip())
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GenerationProviderError(f"ASR 响应非 JSON：{raw[:240]}") from exc
        text = str(data.get("text", "")).strip()
        if not text:
            raise GenerationProviderError("ASR 返回空文本")
        duration = data.get("duration")
        return TranscriptionResult(
            text=text,
            language=str(data.get("language", "")).strip(),
            duration_seconds=float(duration) if isinstance(duration, int | float) else None,
            raw=data,
        )

    return await asyncio.to_thread(_send)


_ASR_DISPATCH: dict[str, object] = {
    "openai_transcriptions": _openai_transcriptions,
}
