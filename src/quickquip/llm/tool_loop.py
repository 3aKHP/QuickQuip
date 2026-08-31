from __future__ import annotations

import asyncio

from quickquip.llm.provider import LLMProviderError, LLMRequest, _is_retryable
from quickquip.llm.provider.trace import trace_agent_loop
from quickquip.llm.tool_discovery import ToolDiscovery
from quickquip.llm.tool_result_pipeline import ToolResultPipeline
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


@trace_agent_loop
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
    image_preprocessor=None,
):
    client = build_provider_client(provider)
    max_rounds = max(0, min(runtime_config.tool_max_rounds, 16))
    max_calls = max(1, min(runtime_config.tool_max_calls_per_round, 32))
    retry_max = max(1, getattr(runtime_config, "retry_max_attempts", 3))
    retry_delay = max(0.0, getattr(runtime_config, "retry_base_delay", 1.0))
    effective_search_max_calls = max(1, min(search_max_calls_per_round, search_failsafe_max_calls_per_round))
    current_request = request
    counted_rounds = 0
    discovery = ToolDiscovery(
        enabled=tool_discovery_enabled,
        tool_registry=tool_registry,
        tool_search_name=tool_search_name,
        tool_list_name=tool_list_name,
        enabled_tool_names=enabled_tool_names,
        initial_tool_names=initial_tool_names,
        search_limit=tool_discovery_search_limit,
        max_loaded_tools=tool_discovery_max_loaded_tools,
        request_tools=request.tools,
    )
    result_pipeline = ToolResultPipeline(
        provider=provider,
        request=request,
        context=context,
        image_preprocessor=image_preprocessor,
    )

    if tool_discovery_enabled:
        current_request = LLMRequest(
            model=current_request.model,
            system_prompt=current_request.system_prompt,
            messages=current_request.messages,
            temperature=current_request.temperature,
            max_output_tokens=current_request.max_output_tokens,
            thinking_budget=current_request.thinking_budget,
            tools=discovery.loaded_specs(current_request.tools),
            allow_tool_calls=current_request.allow_tool_calls,
            tool_choice=current_request.tool_choice,
            builtin_search=current_request.builtin_search,
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

        limited_calls = [
            *search_calls[:effective_search_max_calls],
            *other_calls[:max_calls],
        ]

        if provider.protocol == "gemini":
            if len(limited_calls) != len(response.tool_calls):
                logger.warning(
                    "Gemini tool batch rejected (fail-closed): provider=%s model=%s requested=%d kept=0",
                    provider.id,
                    response.model,
                    len(response.tool_calls),
                )
                # 整批拒绝的提示必须追加而非兜底：模型附带的叙述文本不应顶替拒绝说明。
                notice = "模型一次请求了过多工具，已拒绝执行不完整的 Gemini 工具批次。"
                response.text = "\n".join(part for part in (response.text, notice) if part)
                response.tool_calls = []
                return response
            # Gemini binds functionResponse batches to the preceding ordered
            # functionCall parts. Keep the provider's order when the full batch
            # is within local limits.
            selected_calls = list(response.tool_calls)
        else:
            selected_calls = limited_calls

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
        result_pipeline.begin_round()
        for call in selected_calls:
            if tool_discovery_enabled and not discovery.is_loaded(call.name):
                tool_results.append(
                    LLMToolResult(
                        call_id=call.id,
                        name=call.name,
                        content=f"工具 {call.name} 尚未加载，请先调用 {tool_search_name} 搜索并加载相关工具。",
                        is_error=True,
                    )
                )
                continue

            blocked_result = result_pipeline.check_call_arguments(call)
            if blocked_result is not None:
                tool_results.append(blocked_result)
                continue

            result = await tool_registry.execute(call, context)
            result = await result_pipeline.process_result(call, result)
            tool_results.append(result)
            if tool_discovery_enabled and call.name == tool_search_name and not result.is_error:
                newly_loaded = discovery.load_from_search_call(call)
                if newly_loaded:
                    logger.info(
                        "LLM tool discovery loaded tools: provider=%s model=%s names=%s",
                        provider.id,
                        response.model,
                        newly_loaded,
                    )
            if tool_discovery_enabled and call.name == tool_list_name and not result.is_error:
                newly_loaded = discovery.load_from_list_call(call)
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
                inline_images=list(item.images),
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
            tools=discovery.loaded_specs(current_request.tools),
            allow_tool_calls=current_request.allow_tool_calls,
            tool_choice=current_request.tool_choice,
            builtin_search=current_request.builtin_search,
        )

    raise RuntimeError("工具调用循环未按预期结束")
