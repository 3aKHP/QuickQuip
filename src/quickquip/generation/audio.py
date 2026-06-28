from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
import re
import ssl
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


def _ssl_context():
    try:
        import certifi
    except ModuleNotFoundError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


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
            with request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
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
            with request.urlopen(
                http_request,
                timeout=timeout,
                context=_ssl_context(),
            ) as response:
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
    # 本地/自建 TTS 协议无音色查询 API：返回空，不报错。
    # 若 model config 在 extra_body 配置了静态 voices 列表，直接返回。
    if provider.protocol in {"openai_tts", "http_tts"}:
        static_voices: list[VoiceInfo] = []
        for model in provider.models:
            voices = model.extra_body.get("voices") if isinstance(model.extra_body, dict) else None
            if not isinstance(voices, list):
                continue
            for item in voices:
                if isinstance(item, str):
                    static_voices.append(VoiceInfo(voice_id=item, source=provider.id))
                elif isinstance(item, dict):
                    vid = str(item.get("voice_id", "")).strip()
                    if vid:
                        static_voices.append(
                            VoiceInfo(
                                voice_id=vid,
                                voice_name=str(item.get("voice_name", "")),
                                source=provider.id,
                            )
                        )
        return {"static": static_voices} if static_voices else {}
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


def _build_local_headers(provider: AudioProviderConfig) -> dict[str, str]:
    """本地/自建 TTS 服务的请求头：仅在配置了 api_key_env 时才附加鉴权。"""
    headers = {**provider.headers}
    if provider.user_agent:
        headers["User-Agent"] = provider.user_agent
    if provider.api_key_env:
        api_key = os.getenv(provider.api_key_env, "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    return headers


async def _http_raw_bytes(
    url: str,
    *,
    headers: dict,
    payload: dict | None,
    timeout: float,
    method: str = "POST",
) -> tuple[bytes, str]:
    """发送 JSON 请求并读取 raw bytes 响应体（用于响应为音频流的 TTS）。返回 (bytes, mime_type)。"""
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = dict(headers)
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    http_request = request.Request(url=url, data=body, headers=request_headers, method=method)

    def _send() -> tuple[bytes, str]:
        try:
            with request.urlopen(http_request, timeout=timeout, context=_ssl_context()) as response:
                mime_type = response.headers.get_content_type() or "application/octet-stream"
                return response.read(), mime_type
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GenerationProviderError(f"HTTP {exc.code} {detail[:240]}") from exc
        except error.URLError as exc:
            raise GenerationProviderError(f"网络错误：{exc.reason}") from exc
        except OSError as exc:
            raise GenerationProviderError(f"网络错误：{exc}") from exc

    return await asyncio.to_thread(_send)


# {text} / {voice} 占位符单次替换（防顺序替换注入：用户文本含 {voice} 不会被替换）
_PLACEHOLDER_RE = re.compile(r"\{text\}|\{voice\}")


def _substitute_placeholders(value: object, *, text: str, voice: str) -> object:
    """对模板字段值做 {text} / {voice} 单次正则替换；非字符串原样返回。"""
    if not isinstance(value, str):
        return value
    return _PLACEHOLDER_RE.sub(lambda m: text if m.group() == "{text}" else voice, value)


async def _openai_tts(
    provider: AudioProviderConfig,
    model_config: AudioModelConfig,
    text: str,
    *,
    voice_id: str | None = None,
) -> GeneratedAudioResult:
    """OpenAI TTS 兼容协议：POST /audio/speech，响应体为音频 bytes。

    覆盖 edge-tts / GPT-SoVITS / piper 等本地服务的 OpenAI 兼容包装。
    """
    url = provider.base_url.rstrip("/") + "/audio/speech"
    payload: dict = {
        "model": model_config.model,
        "input": text,
        "voice": (voice_id or model_config.voice_id or "default").strip(),
    }
    if model_config.format:
        payload["response_format"] = model_config.format
    if model_config.speed:
        payload["speed"] = model_config.speed
    if model_config.extra_body:
        payload.update({k: v for k, v in model_config.extra_body.items() if not k.startswith("__")})
    if provider.extra_body:
        payload.update({k: v for k, v in provider.extra_body.items() if not k.startswith("__")})
    audio_bytes, detected_mime = await _http_raw_bytes(
        url,
        headers=_build_local_headers(provider),
        payload=payload,
        timeout=provider.timeout_seconds,
    )
    if not audio_bytes:
        raise GenerationProviderError("OpenAI TTS 返回空响应")
    mime_type = _mime_for_audio_format(model_config.format) if model_config.format else detected_mime
    return GeneratedAudioResult(
        audio_bytes=audio_bytes,
        mime_type=mime_type,
        format=model_config.format or "mp3",
    )


async def _http_tts(
    provider: AudioProviderConfig,
    model_config: AudioModelConfig,
    text: str,
    *,
    voice_id: str | None = None,
) -> GeneratedAudioResult:
    """原始 HTTP 协议：自定义请求体字段映射，适配非 OpenAI 格式的本地 TTS。

    请求体从 model_config.extra_body 模板派生，支持 {text} / {voice} 占位符替换。
    provider.extra_body 的字符串字段同样支持占位符替换（兜底补充）。
    响应体作为音频 bytes 读取。
    """
    path = str(model_config.extra_body.get("__path", "/tts"))
    if not path.startswith("/"):
        path = "/" + path
    method = str(model_config.extra_body.get("__method", "POST")).upper() or "POST"
    url = provider.base_url.rstrip("/") + path

    resolved_voice = (voice_id or model_config.voice_id or "").strip()

    # 模板字段：复制 extra_body 后剔除下划线开头的内部控制键，做单次正则占位符替换
    template = {k: v for k, v in model_config.extra_body.items() if not k.startswith("__")}
    payload: dict = {
        k: _substitute_placeholders(v, text=text, voice=resolved_voice) for k, v in template.items()
    }
    # provider.extra_body 兜底补充（同样做占位符替换）
    for key, value in provider.extra_body.items():
        payload.setdefault(key, _substitute_placeholders(value, text=text, voice=resolved_voice))

    audio_bytes, detected_mime = await _http_raw_bytes(
        url,
        headers=_build_local_headers(provider),
        payload=payload,
        timeout=provider.timeout_seconds,
        method=method,
    )
    if not audio_bytes:
        raise GenerationProviderError("HTTP TTS 返回空响应")
    mime_type = detected_mime
    if mime_type == "application/json" and model_config.format:
        mime_type = _mime_for_audio_format(model_config.format)
    return GeneratedAudioResult(
        audio_bytes=audio_bytes,
        mime_type=mime_type,
        format=model_config.format or "wav",
    )


_AUDIO_DISPATCH: dict[str, object] = {
    "minimax_t2a_http": _minimax_t2a_http,
    "minimax_t2a_async": _minimax_t2a_async,
    "openai_tts": _openai_tts,
    "http_tts": _http_tts,
}
