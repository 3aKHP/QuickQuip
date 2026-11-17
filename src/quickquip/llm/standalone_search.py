"""Request-owned execution of the Responses standalone web tool."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json

import httpx
from typing import Awaitable, Callable

from quickquip.llm.provider.owner import resolve_wire_model
from quickquip.llm.tools import LLMInlineImage, LLMToolOutput, LLMToolSpec, ToolExecutionContext
from quickquip.search.responses_web import (
    DESCRIPTION,
    MAX_OPERATIONS,
    PROFILE_ID,
    TOOL_NAME,
    bound_output,
    command_schema,
    operation_count,
    read_result,
    validate_commands,
)


@dataclass(slots=True)
class WebRun:
    post: Callable[[dict], Awaitable[dict]]
    session_id: str
    model: str
    recent: list[dict]
    operations: int = 0
    token_budget: int = 8192
    batch_rejected: bool = False

    async def execute(self, commands: dict) -> LLMToolOutput:
        async with asyncio.timeout(120):
            return await self._execute(commands)

    async def _execute(self, commands: dict) -> LLMToolOutput:
        if self.batch_rejected:
            return LLMToolOutput("搜索批次超过本次回复的操作上限，未执行。", is_error=True)
        if self.token_budget < 64:
            return LLMToolOutput("本轮上下文不足以容纳搜索材料。", is_error=True)
        validate_commands(commands)
        count = operation_count(commands)
        if not count:
            return LLMToolOutput("搜索命令为空。", is_error=True)
        if self.operations + count > MAX_OPERATIONS:
            return LLMToolOutput("本次回复的搜索操作已达上限。", is_error=True)
        # Charge before awaiting: parallel calls and failed attempts share the quota.
        self.operations += count
        from copy import deepcopy

        wire_commands = deepcopy(commands)
        for sport in wire_commands.get("sports", []):
            sport.setdefault("tool", "sports")
        payload = {
            "id": self.session_id,
            "model": self.model,
            "commands": wire_commands,
            "input": self.recent,
            "max_output_tokens": min(4096, self.token_budget),
            "settings": {"external_web_access": True, "allowed_callers": ["direct"]},
        }
        body = await self.post(payload)
        text, sources, failed = read_result(body)
        # Preserve source DTOs with the returned text; both follow tool retention,
        # filtering and frozen replay. Opaque ciphertext lives only in HTTP audit.
        safe_sources = [
            {
                k: row[k][:512]
                for k in ("type", "ref_id", "title", "url")
                if isinstance(row.get(k), str)
            }
            for row in sources[:5]
        ]
        sources_text = json.dumps(safe_sources, ensure_ascii=False)
        content = bound_output(text)
        if sources and len(sources_text.encode()) < 4096:
            content += "\n[搜索来源元数据]\n" + sources_text
        metadata = {
            "version": 1,
            "mode": "responses_standalone",
            "requires_image": "screenshot" in commands,
            "truncated": len(text.encode()) > 24_576,
            "operations": count,
            "sources": safe_sources,
        }
        images = []
        if not failed and any(key in commands for key in ("image_query", "screenshot")):
            from quickquip.search.media import fetch_image, image_urls

            slots = min(3, max(0, (self.token_budget - 256) // 1200))
            for url in image_urls(text, sources)[:slots]:
                try:
                    data, mime = await fetch_image(url)
                    images.append(LLMInlineImage(data, mime, f"search_image_{len(images)}"))
                except (ValueError, OSError, TimeoutError, httpx.HTTPError) as exc:
                    content += f"\n[搜索图片不可读取：{type(exc).__name__}]"
        if "screenshot" in commands and not images:
            content += "\n[搜索端点未返回可读取的截图图片，仅保留引用信息。]"
            failed = True

        from quickquip.llm.token_estimate import estimate_tokens

        budget = max(0, self.token_budget - len(images) * 1200)
        if estimate_tokens(content) > budget:
            low, high = 0, len(content)
            suffix = "\n[搜索材料已按上下文预算截断]"
            while low < high:
                middle = (low + high + 1) // 2
                if estimate_tokens(content[:middle] + suffix) <= budget:
                    low = middle
                else:
                    high = middle - 1
            content = content[:low] + suffix
            metadata["truncated"] = True
        metadata["status"] = "failed" if failed else "completed"
        return LLMToolOutput(content, images=images, is_error=failed, search_metadata=metadata)


def prepare_web_run(provider, request, client) -> WebRun | None:
    if provider.protocol != "openai_responses" or provider.responses_profile != PROFILE_ID:
        return None
    if not request.allow_tool_calls or not request.builtin_search or request.session is None:
        return None
    wire_model = resolve_wire_model(provider, request.model)
    identity = json.dumps(
        [
            request.session.id,
            provider.id,
            provider.base_url,
            wire_model,
            provider.responses_profile,
            request.epoch_id,
        ],
        separators=(",", ":"),
    )
    recent = []
    user_indexes = [i for i, m in enumerate(request.messages) if m.role == "user"]
    start = user_indexes[-2] if len(user_indexes) >= 2 else (user_indexes[0] if user_indexes else 0)
    from quickquip.llm.token_estimate import estimate_tokens

    assistant_remaining = 1000
    for message in request.messages[start:]:
        if message.role not in {"user", "assistant"} or not message.content:
            continue
        text = message.content
        if message.role == "assistant":
            low, high = 0, len(text)
            while low < high:
                middle = (low + high + 1) // 2
                if estimate_tokens(text[:middle]) <= assistant_remaining:
                    low = middle
                else:
                    high = middle - 1
            text = text[:low]
            assistant_remaining -= estimate_tokens(text)
        if text:
            recent.append({"role": message.role, "content": text})

    async def post(payload: dict) -> dict:
        return await client.search_web(payload, request)

    return WebRun(post, hashlib.sha256(identity.encode()).hexdigest(), wire_model, recent)


async def execute_web(commands: dict, context: ToolExecutionContext) -> LLMToolOutput:
    run = context.web_search
    if not isinstance(run, WebRun):
        return LLMToolOutput("当前请求未启用独立搜索。", is_error=True)
    return await run.execute(commands)


def register_web_tool(registry) -> None:
    registry.register(
        LLMToolSpec(TOOL_NAME, DESCRIPTION, command_schema()),
        execute_web,
        category="search",
        keywords=["搜索", "网页", "find", "web"],
        always_loaded=True,
    )


def prepare_web_round(run: object, response, calls, available_tokens: int | None) -> None:
    """Reserve a whole web batch and share remaining context before any HTTP attempt."""
    if not isinstance(run, WebRun):
        return
    from quickquip.llm.token_estimate import estimate_native_blocks_tokens, estimate_tokens

    if available_tokens is not None:
        response_tokens = (
            estimate_native_blocks_tokens(
                response.native_blocks,
                effort=response.owner.extra.get("effort") if response.owner else None,
            )
            if response.native_blocks
            else estimate_tokens(response.text)
        )
        available = max(0, available_tokens - response_tokens)
        run.token_budget = max(0, available // max(1, len(calls)) - 256)
    batch_operations = 0
    for call in calls:
        if call.name == TOOL_NAME:
            try:
                arguments = json.loads(call.arguments_json)
                if isinstance(arguments, dict):
                    batch_operations += operation_count(arguments)
            except (ValueError, TypeError):
                pass  # Registry returns a malformed-argument result.
    run.batch_rejected = run.operations + batch_operations > MAX_OPERATIONS
