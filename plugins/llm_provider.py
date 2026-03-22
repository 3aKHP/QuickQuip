from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import json
from typing import Any
import os
from urllib import error, parse, request

from plugins.llm_config import ProviderConfig


class LLMProviderError(RuntimeError):
    pass


@dataclass(slots=True)
class LLMImageInput:
    source_url: str
    media_type: str
    data_base64: str


@dataclass(slots=True)
class LLMRequest:
    model: str
    system_prompt: str
    history_messages: list[dict[str, str]]
    prompt: str
    image_urls: list[str]
    temperature: float
    max_output_tokens: int


@dataclass(slots=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


def _extract_openai_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "".join(parts).strip()
    return ""


def _extract_claude_text(content: Any) -> str:
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "".join(parts).strip()
    if isinstance(content, str):
        return content.strip()
    return ""


def _extract_gemini_text(candidates: Any) -> str:
    if not isinstance(candidates, list) or not candidates:
        return ""
    candidate = candidates[0]
    content = candidate.get("content", {}) if isinstance(candidate, dict) else {}
    parts = content.get("parts", []) if isinstance(content, dict) else []
    text_parts: list[str] = []
    for item in parts:
        if isinstance(item, dict):
            text_parts.append(str(item.get("text", "")))
    return "".join(text_parts).strip()


class BaseProviderClient:
    def __init__(self, config: ProviderConfig):
        self.config = config

    def _get_api_key(self) -> str:
        api_key = os.getenv(self.config.api_key_env, "").strip()
        if not api_key:
            raise LLMProviderError(
                f"环境变量 {self.config.api_key_env} 未设置，provider {self.config.id} 无法调用"
            )
        return api_key

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError

    async def _download_image(self, image_url: str) -> LLMImageInput:
        http_request = request.Request(image_url, headers={"User-Agent": "QuickQuip/1.0"})

        def _fetch() -> LLMImageInput:
            try:
                with request.urlopen(http_request, timeout=self.config.timeout_seconds) as response:
                    media_type = response.headers.get_content_type() or "image/jpeg"
                    if not media_type.startswith("image/"):
                        raise LLMProviderError(f"图片 URL 不是受支持的图片类型：{image_url}")
                    raw = response.read()
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise LLMProviderError(f"图片下载失败：HTTP {exc.code} {detail[:160]}") from exc
            except error.URLError as exc:
                raise LLMProviderError(f"图片下载网络错误：{exc.reason}") from exc

            if not raw:
                raise LLMProviderError(f"图片内容为空：{image_url}")
            if len(raw) > 5 * 1024 * 1024:
                raise LLMProviderError(f"图片过大，当前限制为 5MB：{image_url}")

            return LLMImageInput(
                source_url=image_url,
                media_type=media_type,
                data_base64=base64.b64encode(raw).decode("ascii"),
            )

        return await asyncio.to_thread(_fetch)

    async def _prepare_image_inputs(self, image_urls: list[str]) -> list[LLMImageInput]:
        if not image_urls:
            return []
        prepared: list[LLMImageInput] = []
        for image_url in image_urls[:3]:
            prepared.append(await self._download_image(image_url))
        return prepared

    async def _post_json(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(url=url, data=body, headers=headers, method="POST")

        def _send() -> dict[str, Any]:
            try:
                with request.urlopen(http_request, timeout=self.config.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw)
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise LLMProviderError(
                    f"HTTP {exc.code} {detail[:240]}"
                ) from exc
            except error.URLError as exc:
                raise LLMProviderError(f"网络错误：{exc.reason}") from exc

        return await asyncio.to_thread(_send)


class OpenAIProviderClient(BaseProviderClient):
    async def complete(self, request: LLMRequest) -> LLMResponse:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._get_api_key()}",
            "Content-Type": "application/json",
            **self.config.headers,
        }
        image_inputs = await self._prepare_image_inputs(request.image_urls)
        current_message_content: str | list[dict[str, Any]]
        if image_inputs:
            current_message_content = [
                *[
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{item.media_type};base64,{item.data_base64}"},
                    }
                    for item in image_inputs
                ],
                {"type": "text", "text": request.prompt},
            ]
        else:
            current_message_content = request.prompt
        payload = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                *request.history_messages,
                {"role": "user", "content": current_message_content},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        data = await self._post_json(url, headers, payload)
        choice = ((data.get("choices") or [{}])[0]).get("message", {})
        text = _extract_openai_text(choice.get("content"))
        usage = data.get("usage", {})
        return LLMResponse(
            text=text,
            model=str(data.get("model", request.model)),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )


class ClaudeProviderClient(BaseProviderClient):
    async def complete(self, request: LLMRequest) -> LLMResponse:
        url = self.config.base_url.rstrip("/") + "/messages"
        headers = {
            "x-api-key": self._get_api_key(),
            "anthropic-version": self.config.headers.get("anthropic-version", "2023-06-01"),
            "Content-Type": "application/json",
            **{k: v for k, v in self.config.headers.items() if k != "anthropic-version"},
        }
        image_inputs = await self._prepare_image_inputs(request.image_urls)
        current_message_content: str | list[dict[str, Any]]
        if image_inputs:
            current_message_content = [
                *[
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": item.media_type,
                            "data": item.data_base64,
                        },
                    }
                    for item in image_inputs
                ],
                {"type": "text", "text": request.prompt},
            ]
        else:
            current_message_content = request.prompt
        payload = {
            "model": request.model,
            "system": request.system_prompt,
            "messages": [
                *request.history_messages,
                {"role": "user", "content": current_message_content},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        data = await self._post_json(url, headers, payload)
        usage = data.get("usage", {})
        return LLMResponse(
            text=_extract_claude_text(data.get("content")),
            model=str(data.get("model", request.model)),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )


class GeminiProviderClient(BaseProviderClient):
    async def complete(self, request: LLMRequest) -> LLMResponse:
        api_key = self._get_api_key()
        url = (
            self.config.base_url.rstrip("/")
            + f"/models/{request.model}:generateContent?key={parse.quote(api_key)}"
        )
        image_inputs = await self._prepare_image_inputs(request.image_urls)
        history = []
        for message in request.history_messages:
            role = "model" if message["role"] == "assistant" else "user"
            history.append(
                {
                    "role": role,
                    "parts": [{"text": message["content"]}],
                }
            )
        current_parts: list[dict[str, Any]] = [
            *[
                {
                    "inline_data": {
                        "mime_type": item.media_type,
                        "data": item.data_base64,
                    }
                }
                for item in image_inputs
            ],
            {"text": request.prompt},
        ]
        history.append({"role": "user", "parts": current_parts})
        payload = {
            "systemInstruction": {"parts": [{"text": request.system_prompt}]},
            "contents": history,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_output_tokens,
            },
        }
        headers = {
            "Content-Type": "application/json",
            **self.config.headers,
        }
        data = await self._post_json(url, headers, payload)
        usage = data.get("usageMetadata", {})
        return LLMResponse(
            text=_extract_gemini_text(data.get("candidates")),
            model=request.model,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
        )


def build_provider_client(config: ProviderConfig) -> BaseProviderClient:
    if config.protocol == "openai":
        return OpenAIProviderClient(config)
    if config.protocol == "claude":
        return ClaudeProviderClient(config)
    if config.protocol == "gemini":
        return GeminiProviderClient(config)
    raise LLMProviderError(f"未知 provider 协议：{config.protocol}")
