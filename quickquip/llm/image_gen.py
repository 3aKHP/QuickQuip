from __future__ import annotations

from urllib import parse

from quickquip.llm.config import ImageGenerationConfig, ProviderConfig
from quickquip.llm.provider import BaseProviderClient, LLMProviderError

_SUPPORTED_PROTOCOLS = frozenset({"openai_images", "gemini_imagen"})


async def generate_image(
    ig_config: ImageGenerationConfig,
    provider: ProviderConfig,
    prompt: str,
) -> str:
    if ig_config.protocol == "openai_images":
        return await _openai_images(ig_config, provider, prompt)
    if ig_config.protocol == "gemini_imagen":
        return await _gemini_imagen(ig_config, provider, prompt)
    raise LLMProviderError(
        f"未知图片生成协议：{ig_config.protocol!r}，支持：{', '.join(sorted(_SUPPORTED_PROTOCOLS))}"
    )


async def _openai_images(
    ig_config: ImageGenerationConfig,
    provider: ProviderConfig,
    prompt: str,
) -> str:
    """OpenAI Images API 格式（兼容 OpenAI DALL-E、GPT Image 系列及火山 Seedream 等）。"""
    client = BaseProviderClient(provider)
    url = provider.base_url.rstrip("/") + "/images/generations"
    headers = {
        **provider.headers,
        "Authorization": f"Bearer {client._get_api_key()}",
        "Content-Type": "application/json",
    }
    if provider.user_agent:
        headers["User-Agent"] = provider.user_agent

    payload: dict = {
        "model": ig_config.model,
        "prompt": prompt,
        "n": 1,
        "size": ig_config.size,
        "quality": ig_config.quality,
        "response_format": "b64_json",
    }
    if provider.extra_body:
        payload.update(provider.extra_body)

    data = await client._post_json_with_fallback(url, headers, payload)

    if "error" in data:
        raise LLMProviderError(data["error"].get("message", str(data["error"])))

    items = data.get("data", [])
    if not items or not items[0].get("b64_json"):
        raise LLMProviderError("图片生成返回空结果")

    return items[0]["b64_json"]


async def _gemini_imagen(
    ig_config: ImageGenerationConfig,
    provider: ProviderConfig,
    prompt: str,
) -> str:
    """Gemini generateContent 格式（Gemini 2.0/Flash 图片生成系列）。"""
    client = BaseProviderClient(provider)
    url = (
        provider.base_url.rstrip("/")
        + f"/models/{ig_config.model}:generateContent"
        + f"?key={parse.quote(client._get_api_key())}"
    )
    headers = {
        **provider.headers,
        "Content-Type": "application/json",
    }
    if provider.user_agent:
        headers["User-Agent"] = provider.user_agent

    payload: dict = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    if provider.extra_body:
        payload.update(provider.extra_body)

    data = await client._post_json_with_fallback(url, headers, payload)

    if "error" in data:
        raise LLMProviderError(data["error"].get("message", str(data["error"])))

    candidates = data.get("candidates", [])
    if not candidates:
        raise LLMProviderError("图片生成返回空结果")

    for part in candidates[0].get("content", {}).get("parts", []):
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return inline["data"]

    raise LLMProviderError("图片生成响应中未找到图片数据")
