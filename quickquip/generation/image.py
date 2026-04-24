from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, replace
import json
import os
from urllib import error, parse, request

from quickquip.generation.config import ImageModelConfig, ImageProviderConfig
from quickquip.generation.errors import GenerationProviderError


@dataclass(slots=True)
class ImageInput:
    data: bytes
    media_type: str = "image/jpeg"


def _get_api_key(provider: ImageProviderConfig) -> str:
    api_key = os.getenv(provider.api_key_env, "").strip()
    if not api_key:
        raise GenerationProviderError(
            f"环境变量 {provider.api_key_env} 未设置，provider {provider.id} 无法调用"
        )
    return api_key


async def download_image(url: str, timeout: float = 20.0) -> ImageInput:
    def _fetch() -> ImageInput:
        try:
            req = request.Request(url, headers={"User-Agent": "QuickQuip/1.0"})
            with request.urlopen(req, timeout=timeout) as resp:
                media_type = resp.headers.get_content_type() or "image/jpeg"
                return ImageInput(data=resp.read(), media_type=media_type)
        except error.HTTPError as exc:
            raise GenerationProviderError(f"图片下载失败：HTTP {exc.code}") from exc
        except error.URLError as exc:
            raise GenerationProviderError(f"图片下载失败：{exc.reason}") from exc
        except OSError as exc:
            raise GenerationProviderError(f"图片下载失败：{exc}") from exc

    return await asyncio.to_thread(_fetch)


async def _http_post(url: str, headers: dict, body: bytes, timeout: float) -> dict:
    http_request = request.Request(url=url, data=body, headers=headers, method="POST")

    def _send() -> dict:
        try:
            with request.urlopen(http_request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise GenerationProviderError(f"响应非 JSON：{raw[:120]}") from exc
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GenerationProviderError(f"HTTP {exc.code} {detail[:240]}") from exc
        except error.URLError as exc:
            raise GenerationProviderError(f"网络错误：{exc.reason}") from exc
        except OSError as exc:
            raise GenerationProviderError(f"网络错误：{exc}") from exc

    return await asyncio.to_thread(_send)


async def _post_json(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    body = json.dumps(payload).encode("utf-8")
    return await _http_post(url, {**headers, "Content-Type": "application/json"}, body, timeout)


async def _openai_extract_image(data: dict) -> str:
    items = data.get("data", [])
    if not items:
        raise GenerationProviderError("图片生成返回空结果")
    item = items[0]
    if item.get("b64_json"):
        return item["b64_json"]
    if item.get("url"):
        img = await download_image(item["url"])
        return base64.b64encode(img.data).decode("ascii")
    raise GenerationProviderError("图片生成返回空结果")


async def generate_image(
    model_config: ImageModelConfig,
    provider: ImageProviderConfig,
    prompt: str,
    *,
    input_images: list[ImageInput] | None = None,
    size: str | None = None,
    quality: str | None = None,
) -> str:
    if size or quality:
        model_config = replace(
            model_config,
            size=size or model_config.size,
            quality=quality or model_config.quality,
        )
    handler = _DISPATCH.get(provider.protocol)
    if handler is None:
        raise GenerationProviderError(
            f"未知图片生成协议：{provider.protocol!r}，支持：{', '.join(sorted(_DISPATCH))}"
        )
    return await handler(provider, model_config, prompt, input_images=input_images or [])


async def _openai_images(
    provider: ImageProviderConfig,
    model_config: ImageModelConfig,
    prompt: str,
    *,
    input_images: list[ImageInput] | None = None,
) -> str:
    if input_images:
        return await _openai_images_edit(provider, model_config, prompt, input_images)

    url = provider.base_url.rstrip("/") + "/images/generations"
    headers = {
        **provider.headers,
        "Authorization": f"Bearer {_get_api_key(provider)}",
    }
    if provider.user_agent:
        headers["User-Agent"] = provider.user_agent

    payload: dict = {
        "model": model_config.model,
        "prompt": prompt,
        "n": 1,
        "size": model_config.size,
    }
    if model_config.quality:
        payload["quality"] = model_config.quality
    if model_config.response_format:
        payload["response_format"] = model_config.response_format
    if provider.extra_body:
        payload.update(provider.extra_body)

    data = await _post_json(url, headers, payload, provider.timeout_seconds)
    if "error" in data:
        raise GenerationProviderError(data["error"].get("message", str(data["error"])))
    return await _openai_extract_image(data)


async def _openai_images_edit(
    provider: ImageProviderConfig,
    model_config: ImageModelConfig,
    prompt: str,
    input_images: list[ImageInput],
) -> str:
    url = provider.base_url.rstrip("/") + "/images/edits"
    api_key = _get_api_key(provider)
    boundary = f"----FormBoundary{os.urandom(8).hex()}"

    def _field(name: str, value: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode()

    parts: list[bytes] = [
        _field("model", model_config.model),
        _field("prompt", prompt),
        _field("n", "1"),
        _field("size", model_config.size),
    ]
    if model_config.quality:
        parts.append(_field("quality", model_config.quality))

    extensions = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    for i, image in enumerate(input_images):
        ext = extensions.get(image.media_type, "jpg")
        header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image[]"; filename="image{i}.{ext}"\r\n'
            f"Content-Type: {image.media_type}\r\n\r\n"
        ).encode()
        parts.append(header + image.data + b"\r\n")

    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)

    headers = {
        **provider.headers,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    if provider.user_agent:
        headers["User-Agent"] = provider.user_agent

    data = await _http_post(url, headers, body, provider.timeout_seconds)
    if "error" in data:
        raise GenerationProviderError(data["error"].get("message", str(data["error"])))
    return await _openai_extract_image(data)


async def _minimax_images(
    provider: ImageProviderConfig,
    model_config: ImageModelConfig,
    prompt: str,
    *,
    input_images: list[ImageInput] | None = None,
) -> str:
    url = provider.base_url.rstrip("/") + "/image_generation"
    headers = {
        **provider.headers,
        "Authorization": f"Bearer {_get_api_key(provider)}",
    }
    if provider.user_agent:
        headers["User-Agent"] = provider.user_agent

    payload: dict = {
        "model": model_config.model,
        "prompt": prompt,
        "response_format": "base64",
    }
    if model_config.size:
        payload["aspect_ratio"] = model_config.size
    if input_images:
        payload["subject_reference"] = [
            {
                "type": "character",
                "image_file": (
                    f"data:{image.media_type};base64,"
                    f"{base64.b64encode(image.data).decode('ascii')}"
                ),
            }
            for image in input_images
        ]
    if provider.extra_body:
        payload.update(provider.extra_body)

    data = await _post_json(url, headers, payload, provider.timeout_seconds)
    base_resp = data.get("base_resp", {})
    if base_resp.get("status_code", 0) != 0:
        raise GenerationProviderError(base_resp.get("status_msg", str(data)))
    images = data.get("data", {}).get("image_base64", [])
    if not images:
        raise GenerationProviderError("图片生成返回空结果")
    return images[0]


async def _gemini_imagen(
    provider: ImageProviderConfig,
    model_config: ImageModelConfig,
    prompt: str,
    *,
    input_images: list[ImageInput] | None = None,
) -> str:
    url = (
        provider.base_url.rstrip("/")
        + f"/models/{model_config.model}:generateContent"
        + f"?key={parse.quote(_get_api_key(provider))}"
    )
    headers = {**provider.headers, "Content-Type": "application/json"}
    if provider.user_agent:
        headers["User-Agent"] = provider.user_agent

    parts: list[dict] = []
    for image in input_images or []:
        parts.append(
            {
                "inlineData": {
                    "mimeType": image.media_type,
                    "data": base64.b64encode(image.data).decode("ascii"),
                }
            }
        )
    if prompt:
        parts.append({"text": prompt})
    if not parts:
        parts.append({"text": ""})

    payload: dict = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    if provider.extra_body:
        payload.update(provider.extra_body)

    data = await _post_json(url, headers, payload, provider.timeout_seconds)
    if "error" in data:
        raise GenerationProviderError(data["error"].get("message", str(data["error"])))

    candidates = data.get("candidates", [])
    if not candidates:
        raise GenerationProviderError("图片生成返回空结果")

    for part in candidates[0].get("content", {}).get("parts", []):
        inline = part.get("inlineData")
        if inline and inline.get("data"):
            return inline["data"]

    raise GenerationProviderError("图片生成响应中未找到图片数据")


_DISPATCH: dict = {
    "openai_images": _openai_images,
    "gemini_imagen": _gemini_imagen,
    "minimax_images": _minimax_images,
}
