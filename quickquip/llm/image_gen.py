from __future__ import annotations

from urllib import parse

from quickquip.llm.config import ImageGenerationConfig, ProviderConfig
from quickquip.llm.provider import BaseProviderClient, LLMProviderError


async def generate_image(
    ig_config: ImageGenerationConfig,
    provider: ProviderConfig,
    prompt: str,
) -> str:
    handler = _DISPATCH.get(ig_config.protocol)
    if handler is None:
        raise LLMProviderError(
            f"未知图片生成协议：{ig_config.protocol!r}，支持：{', '.join(sorted(_DISPATCH))}"
        )
    return await handler(BaseProviderClient(provider), ig_config, prompt)


async def _openai_images(
    client: BaseProviderClient,
    ig_config: ImageGenerationConfig,
    prompt: str,
) -> str:
    url = client.config.base_url.rstrip("/") + "/images/generations"
    headers = {
        **client.config.headers,
        "Authorization": f"Bearer {client._get_api_key()}",
        "Content-Type": "application/json",
    }
    if client.config.user_agent:
        headers["User-Agent"] = client.config.user_agent

    payload: dict = {
        "model": ig_config.model,
        "prompt": prompt,
        "n": 1,
        "size": ig_config.size,
        "quality": ig_config.quality,
        "response_format": "b64_json",
    }
    if client.config.extra_body:
        payload.update(client.config.extra_body)

    data = await client._post_json_with_fallback(url, headers, payload)

    if "error" in data:
        raise LLMProviderError(data["error"].get("message", str(data["error"])))

    items = data.get("data", [])
    if not items or not items[0].get("b64_json"):
        raise LLMProviderError("图片生成返回空结果")

    return items[0]["b64_json"]


async def _gemini_imagen(
    client: BaseProviderClient,
    ig_config: ImageGenerationConfig,
    prompt: str,
) -> str:
    url = (
        client.config.base_url.rstrip("/")
        + f"/models/{ig_config.model}:generateContent"
        + f"?key={parse.quote(client._get_api_key())}"
    )
    headers = {
        **client.config.headers,
        "Content-Type": "application/json",
    }
    if client.config.user_agent:
        headers["User-Agent"] = client.config.user_agent

    payload: dict = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    if client.config.extra_body:
        payload.update(client.config.extra_body)

    data = await client._post_json_with_fallback(url, headers, payload)

    if "error" in data:
        raise LLMProviderError(data["error"].get("message", str(data["error"])))

    candidates = data.get("candidates", [])
    if not candidates:
        raise LLMProviderError("图片生成返回空结果")

    for part in candidates[0].get("content", {}).get("parts", []):
        inline = part.get("inlineData")
        if inline and inline.get("data"):
            return inline["data"]

    raise LLMProviderError("图片生成响应中未找到图片数据")


_DISPATCH: dict = {
    "openai_images": _openai_images,
    "gemini_imagen": _gemini_imagen,
}
