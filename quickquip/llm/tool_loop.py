from __future__ import annotations

from quickquip.llm.provider import LLMRequest
from quickquip.llm.tools import LLMConversationMessage


async def run_tool_call_loop(
    *,
    provider,
    request: LLMRequest,
    context,
    build_provider_client,
    tool_registry,
    runtime_config,
    logger,
    get_search_backend_name,
    search_tool_name: str,
    search_failsafe_max_rounds: int,
    search_failsafe_max_calls_per_round: int,
):
    client = build_provider_client(provider)
    max_rounds = max(0, min(runtime_config.tool_max_rounds, 16))
    max_calls = max(1, min(runtime_config.tool_max_calls_per_round, 32))
    search_backend = get_search_backend_name()
    search_unlimited = search_backend == "searxng"
    current_request = request
    counted_rounds = 0

    for round_index in range(search_failsafe_max_rounds + 1):
        response = await client.complete(current_request)
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

        search_calls = [call for call in response.tool_calls if call.name == search_tool_name]
        other_calls = [call for call in response.tool_calls if call.name != search_tool_name]
        has_non_search_calls = bool(other_calls)

        if has_non_search_calls and counted_rounds >= max_rounds:
            response.text = response.text or "工具调用轮次已达上限，未能完成最终回答。"
            return response

        if search_unlimited:
            selected_calls = [
                *search_calls[:search_failsafe_max_calls_per_round],
                *other_calls[:max_calls],
            ]
        else:
            selected_calls = response.tool_calls[:max_calls]

        if not selected_calls:
            response.text = response.text or "工具调用请求为空，未能完成最终回答。"
            return response

        if has_non_search_calls or not search_unlimited:
            counted_rounds += 1

        if round_index >= search_failsafe_max_rounds:
            response.text = response.text or "联网检索轮次过多，已触发安全上限，未能完成最终回答。"
            return response

        assistant_message = LLMConversationMessage(
            role="assistant",
            content=response.text,
            tool_calls=selected_calls,
        )

        logger.info(
            "LLM tool calls requested: provider=%s model=%s names=%s",
            provider.id,
            response.model,
            [call.name for call in selected_calls],
        )
        tool_results = [await tool_registry.execute(call, context) for call in selected_calls]
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
            tools=current_request.tools,
            allow_tool_calls=current_request.allow_tool_calls,
            tool_choice=current_request.tool_choice,
        )

    raise RuntimeError("工具调用循环未按预期结束")
