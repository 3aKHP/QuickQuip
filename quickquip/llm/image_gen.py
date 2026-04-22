from __future__ import annotations

from quickquip.llm.config import ImageGenerationConfig, ProviderConfig
from quickquip.llm.provider import BaseProviderClient, LLMProviderError


async def generate_image(
    ig_config: ImageGenerationConfig,
    provider: ProviderConfig,
    prompt: str,
) -> str:
    client = BaseProviderClient(provider)
    url = provider.base_url.rstrip("/") + "/images/generations"
    headers = {
        **provider.headers,
        "Authorization": f"Bearer {client._get_api_key()}",
        "Content-Type": "application/json",
    }
    if provider.user_agent:
        headers["User-Agent"] = provider.user_agent

    payload = {
        "model": ig_config.model,
        "prompt": prompt,
        "n": 1,
        "size": ig_config.size,
        "quality": ig_config.quality,
        "response_format": "b64_json",
    }

    data = await client._post_json_with_fallback(url, headers, payload)

    if "error" in data:
        raise LLMProviderError(data["error"].get("message", str(data["error"])))

    items = data.get("data", [])
    if not items or not items[0].get("b64_json"):
        raise LLMProviderError("图片生成返回空结果")

    return items[0]["b64_json"]
