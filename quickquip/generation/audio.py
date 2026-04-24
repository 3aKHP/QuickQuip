from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from urllib import error, parse, request

from quickquip.generation.config import AudioModelConfig, AudioProviderConfig
from quickquip.generation.errors import GenerationProviderError


@dataclass(slots=True)
class GeneratedAudioResult:
    audio_bytes: bytes
    mime_type: str
    format: str
    subtitle: str = ""
    extra_info: dict | None = None


@dataclass(slots=True)
class AudioGenerationTask:
    task_id: str
    task_token: str = ""
    file_id: int | None = None
    status: str = "processing"
    usage_characters: int | None = None


@dataclass(slots=True)
class GeneratedFile:
    file_id: int
    url: str
    mime_type: str = ""
    bytes: bytes | None = None


@dataclass(slots=True)
class VoiceInfo:
    voice_id: str
    voice_name: str = ""
    description: list[str] | None = None
    created_time: str = ""
    source: str = ""


def _get_api_key(provider: AudioProviderConfig) -> str:
    api_key = os.getenv(provider.api_key_env, "").strip()
    if not api_key:
        raise GenerationProviderError(
            f"环境变量 {provider.api_key_env} 未设置，provider {provider.id} 无法调用"
        )
    return api_key


def _mime_for_audio_format(fmt: str) -> str:
    normalized = fmt.strip().lower()
    if normalized == "mp3":
        return "audio/mpeg"
    if normalized == "wav":
        return "audio/wav"
    if normalized == "flac":
        return "audio/flac"
    if normalized == "pcm":
        return "audio/L16"
    return "application/octet-stream"


async def _download_bytes(url: str, timeout: float) -> tuple[bytes, str]:
    def _fetch() -> tuple[bytes, str]:
        try:
            req = request.Request(url, headers={"User-Agent": "QuickQuip/1.0"})
            with request.urlopen(req, timeout=timeout) as resp:
                mime_type = resp.headers.get_content_type() or "application/octet-stream"
                return resp.read(), mime_type
        except error.HTTPError as exc:
            raise GenerationProviderError(f"文件下载失败：HTTP {exc.code}") from exc
        except error.URLError as exc:
            raise GenerationProviderError(f"文件下载失败：{exc.reason}") from exc
        except OSError as exc:
            raise GenerationProviderError(f"文件下载失败：{exc}") from exc

    return await asyncio.to_thread(_fetch)


async def _http_json(
    url: str,
    *,
    method: str,
    headers: dict,
    payload: dict | None,
    timeout: float,
) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = dict(headers)
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    http_request = request.Request(
        url=url,
        data=body,
        headers=request_headers,
        method=method,
    )

    def _send() -> dict:
        try:
            with request.urlopen(http_request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise GenerationProviderError(f"响应非 JSON：{raw[:240]}") from exc
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GenerationProviderError(f"HTTP {exc.code} {detail[:240]}") from exc
        except error.URLError as exc:
            raise GenerationProviderError(f"网络错误：{exc.reason}") from exc
        except OSError as exc:
            raise GenerationProviderError(f"网络错误：{exc}") from exc

    return await asyncio.to_thread(_send)


def _build_headers(provider: AudioProviderConfig) -> dict[str, str]:
    headers = {
        **provider.headers,
        "Authorization": f"Bearer {_get_api_key(provider)}",
    }
    if provider.user_agent:
        headers["User-Agent"] = provider.user_agent
    return headers


def _build_voice_setting(model: AudioModelConfig, *, voice_id: str | None = None) -> dict:
    setting = {
        "voice_id": (voice_id or model.voice_id).strip(),
        "speed": model.speed,
        "vol": model.vol,
        "pitch": model.pitch,
    }
    if model.emotion:
        setting["emotion"] = model.emotion
    if model.voice_modify:
        setting["voice_modify"] = model.voice_modify
    if not setting["voice_id"]:
        raise GenerationProviderError("音频模型未配置默认 voice_id，且命令里也没有提供 --voice")
    return setting


def _build_audio_setting(model: AudioModelConfig, *, async_mode: bool = False) -> dict:
    sample_rate_key = "audio_sample_rate" if async_mode else "sample_rate"
    return {
        sample_rate_key: model.sample_rate,
        "bitrate": model.bitrate,
        "format": model.format,
        "channel": model.channel,
    }


def _build_sync_payload(
    model: AudioModelConfig,
    provider: AudioProviderConfig,
    text: str,
    *,
    voice_id: str | None = None,
) -> dict:
    payload: dict = {
        "model": model.model,
        "text": text,
        "stream": False,
        "voice_setting": _build_voice_setting(model, voice_id=voice_id),
        "audio_setting": _build_audio_setting(model),
        "output_format": model.output_format,
    }
    if model.language_boost:
        payload["language_boost"] = model.language_boost
    if model.subtitle_enable:
        payload["subtitle_enable"] = True
    if model.pronunciation_dict:
        payload["pronunciation_dict"] = model.pronunciation_dict
    if model.extra_body:
        payload.update(model.extra_body)
    if provider.extra_body:
        payload.update(provider.extra_body)
    return payload


async def generate_audio(
    model_config: AudioModelConfig,
    provider: AudioProviderConfig,
    text: str,
    *,
    voice_id: str | None = None,
) -> GeneratedAudioResult:
    handler = _AUDIO_DISPATCH.get(provider.protocol)
    if handler is None:
        raise GenerationProviderError(
            f"未知音频生成协议：{provider.protocol!r}，支持：{', '.join(sorted(_AUDIO_DISPATCH))}"
        )
    return await handler(provider, model_config, text, voice_id=voice_id)


async def _minimax_t2a_http(
    provider: AudioProviderConfig,
    model_config: AudioModelConfig,
    text: str,
    *,
    voice_id: str | None = None,
) -> GeneratedAudioResult:
    url = provider.base_url.rstrip("/") + "/t2a_v2"
    payload = _build_sync_payload(model_config, provider, text, voice_id=voice_id)
    data = await _http_json(
        url,
        method="POST",
        headers=_build_headers(provider),
        payload=payload,
        timeout=provider.timeout_seconds,
    )
    base_resp = data.get("base_resp", {})
    if base_resp.get("status_code", 0) != 0:
        raise GenerationProviderError(base_resp.get("status_msg", str(data)))
    payload_data = data.get("data", {})
    raw_audio = payload_data.get("audio")
    if not raw_audio:
        raise GenerationProviderError("音频生成返回空结果")
    if isinstance(raw_audio, str) and raw_audio.startswith(("http://", "https://")):
        audio_bytes, mime_type = await _download_bytes(raw_audio, timeout=provider.timeout_seconds)
    else:
        if not isinstance(raw_audio, str):
            raise GenerationProviderError("音频生成响应格式异常")
        try:
            audio_bytes = bytes.fromhex(raw_audio)
        except ValueError as exc:
            raise GenerationProviderError("音频数据不是合法的十六进制内容") from exc
        mime_type = _mime_for_audio_format(model_config.format)
    return GeneratedAudioResult(
        audio_bytes=audio_bytes,
        mime_type=mime_type,
        format=model_config.format,
        subtitle=str(payload_data.get("subtitle", "")),
        extra_info=payload_data.get("extra_info") or data.get("extra_info"),
    )


async def create_audio_generation_task(
    model_config: AudioModelConfig,
    provider: AudioProviderConfig,
    text: str,
    *,
    voice_id: str | None = None,
) -> AudioGenerationTask:
    url = provider.base_url.rstrip("/") + "/t2a_async_v2"
    payload = _build_sync_payload(model_config, provider, text, voice_id=voice_id)
    payload["audio_setting"] = _build_audio_setting(model_config, async_mode=True)
    data = await _http_json(
        url,
        method="POST",
        headers=_build_headers(provider),
        payload=payload,
        timeout=provider.timeout_seconds,
    )
    base_resp = data.get("base_resp", {})
    if base_resp.get("status_code", 0) != 0:
        raise GenerationProviderError(base_resp.get("status_msg", str(data)))
    payload_data = data.get("data", {})
    return AudioGenerationTask(
        task_id=str(payload_data.get("task_id", "")).strip(),
        task_token=str(payload_data.get("task_token", "")).strip(),
        file_id=payload_data.get("file_id"),
        status="processing",
        usage_characters=payload_data.get("usage_characters"),
    )


async def query_audio_generation_task(
    provider: AudioProviderConfig,
    task_id: str,
) -> AudioGenerationTask:
    url = (
        provider.base_url.rstrip("/")
        + "/query/t2a_async_query_v2"
        + f"?task_id={parse.quote(task_id)}"
    )
    data = await _http_json(
        url,
        method="GET",
        headers=_build_headers(provider),
        payload=None,
        timeout=provider.timeout_seconds,
    )
    base_resp = data.get("base_resp", {})
    if base_resp.get("status_code", 0) != 0:
        raise GenerationProviderError(base_resp.get("status_msg", str(data)))
    payload_data = data.get("data", {})
    return AudioGenerationTask(
        task_id=task_id,
        task_token=str(payload_data.get("task_token", "")).strip(),
        file_id=payload_data.get("file_id"),
        status=str(payload_data.get("status", "")).strip() or "processing",
        usage_characters=payload_data.get("usage_characters"),
    )


async def retrieve_generated_file(
    provider: AudioProviderConfig,
    file_id: int,
    *,
    download: bool = False,
) -> GeneratedFile:
    url = provider.base_url.rstrip("/") + f"/files/retrieve?file_id={file_id}"
    data = await _http_json(
        url,
        method="GET",
        headers=_build_headers(provider),
        payload=None,
        timeout=provider.timeout_seconds,
    )
    base_resp = data.get("base_resp", {})
    if base_resp.get("status_code", 0) != 0:
        raise GenerationProviderError(base_resp.get("status_msg", str(data)))
    payload_data = data.get("data", {})
    file_url = str(payload_data.get("download_url", "") or payload_data.get("url", "")).strip()
    if not file_url:
        raise GenerationProviderError("文件检索成功，但未返回下载地址")
    file_result = GeneratedFile(
        file_id=file_id,
        url=file_url,
        mime_type=str(payload_data.get("mime_type", "")).strip(),
    )
    if download:
        file_result.bytes, detected_mime = await _download_bytes(file_url, timeout=provider.timeout_seconds)
        if not file_result.mime_type:
            file_result.mime_type = detected_mime
    return file_result


async def list_available_voices(
    provider: AudioProviderConfig,
    *,
    voice_type: str = "all",
) -> dict[str, list[VoiceInfo]]:
    if provider.protocol not in {"minimax_t2a_http", "minimax_t2a_async"}:
        raise GenerationProviderError(f"当前 provider 不支持音色查询：{provider.protocol}")
    url = provider.base_url.rstrip("/") + "/get_voice"
    data = await _http_json(
        url,
        method="POST",
        headers=_build_headers(provider),
        payload={"voice_type": voice_type},
        timeout=provider.timeout_seconds,
    )
    base_resp = data.get("base_resp", {})
    if base_resp.get("status_code", 0) != 0:
        raise GenerationProviderError(base_resp.get("status_msg", str(data)))

    result: dict[str, list[VoiceInfo]] = {}
    for source_key in ("system_voice", "voice_cloning", "voice_generation"):
        items: list[VoiceInfo] = []
        for item in data.get(source_key, []) or []:
            if not isinstance(item, dict):
                continue
            voice_id = str(item.get("voice_id", "")).strip()
            if not voice_id:
                continue
            raw_desc = item.get("description", [])
            descriptions = [str(text).strip() for text in raw_desc if str(text).strip()]
            items.append(
                VoiceInfo(
                    voice_id=voice_id,
                    voice_name=str(item.get("voice_name", "")).strip(),
                    description=descriptions or None,
                    created_time=str(item.get("created_time", "")).strip(),
                    source=source_key,
                )
            )
        result[source_key] = items
    return result


async def _minimax_t2a_async(
    provider: AudioProviderConfig,
    model_config: AudioModelConfig,
    text: str,
    *,
    voice_id: str | None = None,
) -> GeneratedAudioResult:
    task = await create_audio_generation_task(
        model_config,
        provider,
        text,
        voice_id=voice_id,
    )
    for _ in range(60):
        await asyncio.sleep(2)
        status = await query_audio_generation_task(provider, task.task_id)
        if status.status == "success" and status.file_id is not None:
            file_data = await retrieve_generated_file(provider, status.file_id, download=True)
            if not file_data.bytes:
                raise GenerationProviderError("异步音频任务成功，但文件下载为空")
            return GeneratedAudioResult(
                audio_bytes=file_data.bytes,
                mime_type=file_data.mime_type or _mime_for_audio_format(model_config.format),
                format=model_config.format,
            )
        if status.status in {"failed", "expired"}:
            raise GenerationProviderError(f"异步音频任务失败：{status.status}")
    raise GenerationProviderError("异步音频任务轮询超时")


_AUDIO_DISPATCH: dict[str, object] = {
    "minimax_t2a_http": _minimax_t2a_http,
    "minimax_t2a_async": _minimax_t2a_async,
}
