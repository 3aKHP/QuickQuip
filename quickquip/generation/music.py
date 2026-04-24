from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from urllib import error, request

from quickquip.generation.config import MusicModelConfig, MusicProviderConfig
from quickquip.generation.errors import GenerationProviderError


@dataclass(slots=True)
class LyricsGenerationResult:
    title: str = ""
    style_tags: str = ""
    lyrics: str = ""


@dataclass(slots=True)
class GeneratedMusicResult:
    audio_bytes: bytes
    mime_type: str
    format: str
    extra_info: dict | None = None


def _get_api_key(provider: MusicProviderConfig) -> str:
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


def _build_headers(provider: MusicProviderConfig) -> dict[str, str]:
    headers = {
        **provider.headers,
        "Authorization": f"Bearer {_get_api_key(provider)}",
    }
    if provider.user_agent:
        headers["User-Agent"] = provider.user_agent
    return headers


def _build_audio_setting(model: MusicModelConfig) -> dict:
    return {
        "sample_rate": model.sample_rate,
        "bitrate": model.bitrate,
        "format": model.format,
    }


async def generate_lyrics(
    provider: MusicProviderConfig,
    prompt: str,
    *,
    mode: str = "write_full_song",
    lyrics: str = "",
    title: str = "",
) -> LyricsGenerationResult:
    if mode not in {"write_full_song", "edit"}:
        raise GenerationProviderError(f"未知歌词生成模式：{mode}")

    payload: dict[str, object] = {
        "mode": mode,
        "prompt": prompt,
    }
    if lyrics:
        payload["lyrics"] = lyrics
    if title:
        payload["title"] = title
    if provider.extra_body:
        payload.update(provider.extra_body)

    data = await _http_json(
        provider.base_url.rstrip("/") + "/lyrics_generation",
        method="POST",
        headers=_build_headers(provider),
        payload=payload,
        timeout=provider.timeout_seconds,
    )
    base_resp = data.get("base_resp", {})
    if base_resp.get("status_code", 0) != 0:
        raise GenerationProviderError(base_resp.get("status_msg", str(data)))
    return LyricsGenerationResult(
        title=str(data.get("song_title") or data.get("title") or "").strip(),
        style_tags=str(data.get("style_tags", "")).strip(),
        lyrics=str(data.get("lyrics", "")).strip(),
    )


async def generate_music(
    model_config: MusicModelConfig,
    provider: MusicProviderConfig,
    prompt: str,
    *,
    lyrics: str = "",
    instrumental: bool = False,
) -> GeneratedMusicResult:
    payload: dict[str, object] = {
        "model": model_config.model,
        "prompt": prompt,
        "stream": False,
        "output_format": model_config.output_format,
        "audio_setting": _build_audio_setting(model_config),
    }
    if instrumental:
        payload["is_instrumental"] = True
    elif lyrics:
        payload["lyrics"] = lyrics
        if model_config.lyrics_optimizer:
            payload["lyrics_optimizer"] = True
    else:
        raise GenerationProviderError("当前歌曲生成请求缺少歌词")

    if model_config.add_watermark:
        payload["add_watermark"] = True
    if model_config.extra_body:
        payload.update(model_config.extra_body)
    if provider.extra_body:
        payload.update(provider.extra_body)

    data = await _http_json(
        provider.base_url.rstrip("/") + "/music_generation",
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
        raise GenerationProviderError("音乐生成返回空结果")
    if isinstance(raw_audio, str) and raw_audio.startswith(("http://", "https://")):
        audio_bytes, mime_type = await _download_bytes(raw_audio, timeout=provider.timeout_seconds)
    else:
        if not isinstance(raw_audio, str):
            raise GenerationProviderError("音乐生成响应格式异常")
        try:
            audio_bytes = bytes.fromhex(raw_audio)
        except ValueError as exc:
            raise GenerationProviderError("音乐数据不是合法的十六进制内容") from exc
        mime_type = _mime_for_audio_format(model_config.format)
    return GeneratedMusicResult(
        audio_bytes=audio_bytes,
        mime_type=mime_type,
        format=model_config.format,
        extra_info=data.get("extra_info"),
    )
