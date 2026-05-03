from __future__ import annotations

import asyncio
import json

from quickquip.llm.provider import LLMProviderError, LLMRequest, _is_retryable
from quickquip.llm.tools import LLMConversationMessage, LLMToolResult


async def _complete_with_retry(client, request: LLMRequest, *, max_attempts: int, base_delay: float, logger):
    last_exc: LLMProviderError | None = None
    for attempt in range(max_attempts):
        try:
            return await client.complete(request)
        except LLMProviderError as exc:
            last_exc = exc
            if attempt + 1 >= max_attempts or not _is_retryable(exc):
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1, max_attempts, delay, exc,
            )
            await asyncio.sleep(delay)
    raise last_exc  # unreachable, but satisfies type checker


async def run_tool_call_loop(
    *,
    provider,
    request: LLMRequest,
    context,
    build_provider_client,
    tool_registry,
    runtime_config,
    logger,
    search_tool_name: str,
    search_failsafe_max_rounds: int,
    search_failsafe_max_calls_per_round: int,
    search_max_calls_per_round: int = 3,
    tool_discovery_enabled: bool = False,
    tool_search_name: str = "tool_search",
    tool_list_name: str = "tool_list",
    enabled_tool_names: list[str] | None = None,
    initial_tool_names: list[str] | None = None,
    tool_discovery_search_limit: int = 5,
    tool_discovery_max_loaded_tools: int = 12,
):
    client = build_provider_client(provider)
    max_rounds = max(0, min(runtime_config.tool_max_rounds, 16))
    max_calls = max(1, min(runtime_config.tool_max_calls_per_round, 32))
    retry_max = max(1, getattr(runtime_config, "retry_max_attempts", 3))
    retry_delay = max(0.0, getattr(runtime_config, "retry_base_delay", 1.0))
    effective_search_max_calls = max(1, min(search_max_calls_per_round, search_failsafe_max_calls_per_round))
    current_request = request
    counted_rounds = 0
    enabled_names = [name for name in enabled_tool_names or [] if name.strip()]
    loaded_names = [name for name in initial_tool_names or [] if name.strip()]
    if not loaded_names:
        loaded_names = [spec.name for spec in request.tools]
    max_loaded_tools = max(1, min(tool_discovery_max_loaded_tools, 64))
    discovery_search_limit = max(1, min(tool_discovery_search_limit, 20))

    def _loaded_request_tools():
        if not tool_discovery_enabled:
            return current_request.tools
        return tool_registry.get_specs(loaded_names)

    def _append_loaded_tool(name: str) -> bool:
        if name in loaded_names:
            return False
        if enabled_names and name not in enabled_names:
            return False
        if len(loaded_names) >= max_loaded_tools:
            return False
        loaded_names.append(name)
        return True

    def _discover_tools_from_call(call) -> list[str]:
        try:
            arguments = json.loads(call.arguments_json or "{}")
        except json.JSONDecodeError:
            return []
        query = str(arguments.get("query", "")).strip()
        category = str(arguments.get("category", "")).strip()
        try:
            limit = int(arguments.get("limit", discovery_search_limit) or discovery_search_limit)
        except (TypeError, ValueError):
            limit = discovery_search_limit
        matches = tool_registry.search_manifest(
            query,
            enabled_names=enabled_names or None,
            exclude_names=[tool_search_name],
            category=category,
            limit=max(1, min(limit, discovery_search_limit)),
        )
        loaded: list[str] = []
        for entry in matches:
            if _append_loaded_tool(entry.name):
                loaded.append(entry.name)
        return loaded

    def _load_tools_from_list_call(call) -> list[str]:
        try:
            arguments = json.loads(call.arguments_json or "{}")
        except json.JSONDecodeError:
            return []
        mode = str(arguments.get("mode", "")).strip().lower()
        if mode != "load":
            return []
        raw_names = arguments.get("names", [])
        if not isinstance(raw_names, list):
            return []
        loaded: list[str] = []
        for raw_name in raw_names[:discovery_search_limit]:
            name = str(raw_name).strip()
            if not name or name == tool_list_name or name == tool_search_name:
                continue
            if not tool_registry.has_tool(name):
                continue
            if _append_loaded_tool(name):
                loaded.append(name)
        return loaded

    if tool_discovery_enabled:
        current_request = LLMRequest(
            model=current_request.model,
            system_prompt=current_request.system_prompt,
            messages=current_request.messages,
            temperature=current_request.temperature,
            max_output_tokens=current_request.max_output_tokens,
            thinking_budget=current_request.thinking_budget,
            tools=_loaded_request_tools(),
            allow_tool_calls=current_request.allow_tool_calls,
            tool_choice=current_request.tool_choice,
        )

    for round_index in range(search_failsafe_max_rounds + 1):
        response = await _complete_with_retry(
            client, current_request,
            max_attempts=retry_max, base_delay=retry_delay, logger=logger,
        )
        logger.info(
            "LLM completion: provider=%s model=%s finish_reason=%s tool_calls=%s round=%s",
            provider.id,
            response.model,
            response.finish_reason,
            len(response.tool_calls),
            round_index,
        )
        if not response.tool_calls or not current_request.allow_tool_calls:
            return response

        meta_tool_names = {search_tool_name, tool_search_name, tool_list_name}
        search_calls = [call for call in response.tool_calls if call.name == search_tool_name]
        other_calls = [call for call in response.tool_calls if call.name != search_tool_name]
        counted_calls = [call for call in other_calls if call.name not in meta_tool_names]
        has_counted_calls = bool(counted_calls)

        if has_counted_calls and counted_rounds >= max_rounds:
            response.text = response.text or "工具调用轮次已达上限，未能完成最终回答。"
            return response

        selected_calls = [
            *search_calls[:effective_search_max_calls],
            *other_calls[:max_calls],
        ]

        if not selected_calls:
            response.text = response.text or "工具调用请求为空，未能完成最终回答。"
            return response

        if has_counted_calls:
            counted_rounds += 1

        if round_index >= search_failsafe_max_rounds:
            response.text = response.text or "联网检索轮次过多，已触发安全上限，未能完成最终回答。"
            return response

        assistant_message = LLMConversationMessage(
            role="assistant",
            content=response.text,
            tool_calls=selected_calls,
            thinking_blocks=response.thinking_blocks,
        )

        logger.info(
            "LLM tool calls requested: provider=%s model=%s names=%s",
            provider.id,
            response.model,
            [call.name for call in selected_calls],
        )
        tool_results: list[LLMToolResult] = []
        for call in selected_calls:
            if tool_discovery_enabled and call.name not in loaded_names:
                tool_results.append(
                    LLMToolResult(
                        call_id=call.id,
                        name=call.name,
                        content=f"工具 {call.name} 尚未加载，请先调用 {tool_search_name} 搜索并加载相关工具。",
                        is_error=True,
                    )
                )
                continue
            result = await tool_registry.execute(call, context)
            tool_results.append(result)
            if tool_discovery_enabled and call.name == tool_search_name and not result.is_error:
                newly_loaded = _discover_tools_from_call(call)
                if newly_loaded:
                    logger.info(
                        "LLM tool discovery loaded tools: provider=%s model=%s names=%s",
                        provider.id,
                        response.model,
                        newly_loaded,
                    )
            if tool_discovery_enabled and call.name == tool_list_name and not result.is_error:
                newly_loaded = _load_tools_from_list_call(call)
                if newly_loaded:
                    logger.info(
                        "LLM tool list loaded tools: provider=%s model=%s names=%s",
                        provider.id,
                        response.model,
                        newly_loaded,
                    )
        tool_messages = [
            LLMConversationMessage(
                role="tool",
                content=item.content,
                tool_call_id=item.call_id,
                tool_name=item.name,
                is_tool_error=item.is_error,
            )
            for item in tool_results
        ]

        current_request = LLMRequest(
            model=current_request.model,
            system_prompt=current_request.system_prompt,
            messages=[*current_request.messages, assistant_message, *tool_messages],
            temperature=current_request.temperature,
            max_output_tokens=current_request.max_output_tokens,
            thinking_budget=current_request.thinking_budget,
            tools=_loaded_request_tools(),
            allow_tool_calls=current_request.allow_tool_calls,
            tool_choice=current_request.tool_choice,
        )

    raise RuntimeError("工具调用循环未按预期结束")
