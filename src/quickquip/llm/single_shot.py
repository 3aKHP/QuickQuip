"""一次性生成入口（single-shot）的共享管线骨架（v1.12.1 P6 自 ``service.py`` 抽出）。

三条入口共享同一条管线：normalize → 敏感输入扫描 → load_error 守卫 →
provider 守卫 → prompt pack → 单次请求 → 解析 + 输出敏感扫描 → 结果装配。
管线本体统一在本模块；各入口的差异点（prompt builder、解析器、temperature、
rate_limit_key/rule_name、扫描 channel、usage_scope 记账名、降级文案）通过
``CommandSingleShotSpec`` 显式传入。结果装配的两种范式不拉平：命令入口
（defectify/turmfluch）降级返回 dict，card_le_nearest 降级返回 None。

窄接口契约：函数接收显式参数，不接收 ``LLMService`` 实例。
``client_builder`` / ``get_sensitive`` / ``resolve_scope_key`` /
``resolve_settings`` / ``merge_image_urls`` 由调用方
（``quickquip.llm.service``）以惰性 callable 注入，既保持求值顺序与
原实现一致，也保持既有 patch 点（``quickquip.llm.service.build_provider_client``
与 ``quickquip.llm.service._get_sensitive_filter``）有效。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import logging
from typing import Any, Protocol

from quickquip.common.sensitive_filter import (
    DEFAULT_BLOCK_REPLY,
    DEFAULT_OUTPUT_FALLBACK,
    SensitiveFilter,
    scan_and_log,
)
from quickquip.llm.config import LLMConfig, ProviderConfig
from quickquip.llm.provider import (
    BaseProviderClient,
    LLMProviderError,
    LLMRequest,
    strip_leading_reasoning_content,
)
from quickquip.llm.settings import ResolvedGroupSettings
from quickquip.llm.tools import LLMConversationMessage
from quickquip.llm.usage import usage_scope
from quickquip.sts.formulas.card_le.parsing import extract_card_le_name
from quickquip.sts.formulas.card_le.prompting import build_nearest_prompt

logger = logging.getLogger(__name__)

ClientBuilder = Callable[[ProviderConfig], BaseProviderClient]
ResponseParser = Callable[[str], str | None]


class SingleShotPrompt(Protocol):
    """各入口 prompt pack 的最小结构契约（system + user 两段）。"""

    system_prompt: str
    user_prompt: str


@dataclass(frozen=True, slots=True)
class CommandSingleShotSpec:
    """命令型一次性入口（defectify/turmfluch）的差异点束。

    ``response_parser`` 接收 strip 后的模型原始文本，返回最终回复文本；
    返回 None 表示解析失败，走 ``invalid_reply`` 降级。
    ``log_label`` 非 None 时在 provider 调用异常路径记日志
    （turmfluch 记 warning/exception，defectify 不记）。
    """

    rate_limit_key: str
    rule_name: str
    usage_reply: str
    invalid_reply: str
    temperature: float
    input_channel: str
    output_channel: str
    usage_scope_name: str
    prompt_builder: Callable[..., SingleShotPrompt]
    response_parser: ResponseParser
    log_label: str | None = None


def _build_request(
    *,
    provider: ProviderConfig,
    model: str,
    prompt_pack: SingleShotPrompt,
    temperature: float,
    image_urls: list[str] | None = None,
) -> LLMRequest:
    return LLMRequest(
        model=model,
        system_prompt=prompt_pack.system_prompt,
        messages=[
            LLMConversationMessage(
                role="user",
                content=prompt_pack.user_prompt,
                image_urls=list(image_urls or []),
            )
        ],
        temperature=temperature,
        # 不限小预算：推理模型的 reasoning_content 计入 max_tokens
        max_output_tokens=provider.max_output_tokens,
        thinking_budget=None,
        tools=[],
        allow_tool_calls=False,
        tool_choice="none",
    )


def _early_result(spec: CommandSingleShotSpec, reply: str) -> dict[str, Any]:
    """provider 调用前的降级：4 键契约（无 provider_id/model）。"""
    return {
        "reply": reply,
        "rate_limit_key": spec.rate_limit_key,
        "rule_name": spec.rule_name,
        "llm_used": False,
    }


def _llm_result(
    spec: CommandSingleShotSpec, reply: str, *, provider_id: str, model: str
) -> dict[str, Any]:
    """到达 provider 调用后的结果：6 键契约（llm_used 恒为 True）。"""
    return {
        "reply": reply,
        "rate_limit_key": spec.rate_limit_key,
        "rule_name": spec.rule_name,
        "llm_used": True,
        "provider_id": provider_id,
        "model": model,
    }


async def run_command_single_shot(
    *,
    spec: CommandSingleShotSpec,
    config: LLMConfig,
    chat_id: int | str,
    resolve_scope_key: Callable[[], str],
    resolve_settings: Callable[[], ResolvedGroupSettings],
    get_sensitive: Callable[[], SensitiveFilter],
    client_builder: ClientBuilder,
    merge_image_urls: Callable[..., list[str]],
    prompt: str,
    image_urls: list[str] | None,
    quoted_text: str,
    quoted_image_urls: list[str] | None,
    quoted_sender_name: str,
    quoted_user_id: str,
) -> dict[str, Any]:
    """命令型一次性入口的共享管线（defectify/turmfluch 共用）。

    降级一律返回 dict：provider 调用前 4 键，调用后 6 键。
    """
    normalized_prompt = prompt.strip()
    normalized_image_urls = [url.strip() for url in (image_urls or []) if url.strip()]
    normalized_quoted_text = quoted_text.strip()
    normalized_quoted_image_urls = [url.strip() for url in (quoted_image_urls or []) if url.strip()]
    if (
        not normalized_prompt
        and not normalized_image_urls
        and not normalized_quoted_text
        and not normalized_quoted_image_urls
    ):
        return _early_result(spec, spec.usage_reply)

    scope_key = resolve_scope_key()
    sensitive = get_sensitive()
    input_blob = "\n".join(
        part for part in (normalized_prompt, normalized_quoted_text) if part
    )
    input_scan = scan_and_log(
        input_blob,
        channel=spec.input_channel,
        scope=scope_key,
        sensitive_filter=sensitive,
    )
    if input_scan.blocked:
        return _early_result(spec, DEFAULT_BLOCK_REPLY)

    if config.load_error:
        return _early_result(spec, f"LLM 配置不可用：{config.load_error}")

    settings = resolve_settings()
    provider = config.providers.get(settings.provider_id)
    if provider is None:
        return _early_result(spec, f"当前 provider 不存在：{settings.provider_id}")

    prompt_pack = spec.prompt_builder(
        prompt=normalized_prompt,
        image_urls=normalized_image_urls,
        quoted_text=normalized_quoted_text,
        quoted_image_urls=normalized_quoted_image_urls,
        quoted_sender_name=quoted_sender_name,
        quoted_user_id=quoted_user_id,
    )
    effective_image_urls = merge_image_urls(normalized_image_urls, normalized_quoted_image_urls)
    request = _build_request(
        provider=provider,
        model=settings.model or provider.default_model,
        prompt_pack=prompt_pack,
        temperature=spec.temperature,
        image_urls=effective_image_urls,
    )

    try:
        with usage_scope(spec.usage_scope_name, group_id=str(chat_id)):
            response = await client_builder(replace(provider, stream_enabled=False)).complete(request)
    except LLMProviderError as exc:
        if spec.log_label is not None:
            logger.warning("%s LLM call failed: %s", spec.log_label, exc)
        return _llm_result(
            spec, f"LLM 调用失败：{exc}", provider_id=provider.id, model=request.model
        )
    except Exception as exc:
        if spec.log_label is not None:
            logger.exception("%s LLM call raised unexpectedly", spec.log_label)
        return _llm_result(
            spec, f"LLM 调用异常：{exc}", provider_id=provider.id, model=request.model
        )

    raw_text = strip_leading_reasoning_content(response.text).strip()
    text = spec.response_parser(raw_text)
    if text is None:
        return _llm_result(spec, spec.invalid_reply, provider_id=provider.id, model=request.model)
    output_scan = scan_and_log(
        text,
        channel=spec.output_channel,
        scope=scope_key,
        sensitive_filter=sensitive,
    )
    if output_scan.blocked:
        text = DEFAULT_OUTPUT_FALLBACK
    return _llm_result(spec, text, provider_id=provider.id, model=request.model)


async def run_card_le_nearest(
    *,
    config: LLMConfig,
    chat_id: int | str,
    resolve_scope_key: Callable[[], str],
    get_sensitive: Callable[[], SensitiveFilter],
    client_builder: ClientBuilder,
    captured: str,
) -> dict[str, Any] | None:
    """被动路径：为不合法的「{captured}了」找最近真名。

    所有降级路径返回 None（不返回降级 dict）。走
    ``[triggers.quick_judge]`` 配置的专用便宜模型，不走群主模型。
    """
    if config.load_error:
        return None
    qj = config.quick_judge
    provider_id = qj.provider_id if qj.provider_id else config.runtime.default_provider
    if not provider_id or provider_id not in config.providers:
        provider_id = next(iter(config.providers), None)
    if not provider_id:
        return None
    provider = config.providers[provider_id]
    scope_key = resolve_scope_key()
    sensitive = get_sensitive()
    if scan_and_log(
        captured, channel="card_le_input", scope=scope_key, sensitive_filter=sensitive
    ).blocked:
        return None

    prompt_pack = build_nearest_prompt(captured=captured)
    request = _build_request(
        provider=provider,
        model=qj.model if qj.model else provider.default_model,
        prompt_pack=prompt_pack,
        temperature=0.5,  # 最近匹配偏低温求稳
    )
    try:
        with usage_scope("card_le_nearest", group_id=str(chat_id)):
            response = await client_builder(replace(provider, stream_enabled=False)).complete(request)
    except Exception:
        logger.exception("STS card_le nearest LLM call failed for %r", captured)
        return None

    name = extract_card_le_name(strip_leading_reasoning_content(response.text).strip())
    if name is None:
        return None
    text = f"{name}了"
    if scan_and_log(
        text, channel="card_le_output", scope=scope_key, sensitive_filter=sensitive
    ).blocked:
        return None
    return {"reply": text, "llm_used": True, "provider_id": provider.id, "model": request.model}
