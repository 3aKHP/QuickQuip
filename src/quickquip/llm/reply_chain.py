"""回复主链的装配与产出 shaping（自 ``service.py`` 拆出的编排件）。

本模块只收显式参数，不 import ``LLMService``：历史加载、信封渲染、
messages 拼装等运行时依赖由 service 调用点以绑定可调用现取，敏感词
过滤器以解析后的对象传入——``quickquip.llm.service._get_sensitive_filter``
等模块级 patch 点保持在 service.py 内有效。
"""
from __future__ import annotations

import re
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from quickquip.common.sensitive_filter import (
    DEFAULT_OUTPUT_FALLBACK,
    SensitiveFilter,
    log_hits as _log_sensitive_hits,
)
from quickquip.llm.image_preprocessor import ImageDescription
from quickquip.llm.rendering import append_web_search_source_block
from quickquip.llm.reply_types import ChatTurnRequest, ReplyResult
from quickquip.llm.provider import LLMRequest, strip_leading_reasoning_content

if TYPE_CHECKING:
    from quickquip.llm.config import ProviderConfig
    from quickquip.llm.epoch import EpochKey, EpochParams
    from quickquip.llm.provider import LLMResponse
    from quickquip.llm.settings import ResolvedGroupSettings
    from quickquip.llm.tools import LLMConversationMessage, LLMToolSpec

logger = logging.getLogger(__name__)

LLM_RULE_NAME = "llm_chat"
MAX_QUOTED_MESSAGE_CHARS = 1200
MAX_PERSISTED_IMAGE_DESC_CHARS = 200
MAX_PERSISTED_IMAGE_DESC_BLOB_CHARS = 800

BUDGET_EXCEEDED_REPLY = (
    "这次对话的上下文已经太长，无法安全发起模型请求，请用清空上下文命令重置后再试。"
)

_EMPTY_IMAGE_PROMPT = "请描述这张图片，并优先回答群友最可能想知道的内容。"


def reply_result(
    reply: str,
    *,
    llm_used: bool,
    provider_id: str | None = None,
    model: str | None = None,
    images: list[str] | None = None,
    scope_key: str | None = None,
    agent_turn_row_id: int | None = None,
    cancelled_reason: str | None = None,
) -> ReplyResult:
    """回复返回 dict 的唯一构造点：基础四键恒在，其余键按路径显式携带。"""
    result: ReplyResult = {
        "reply": reply,
        "rate_limit_key": LLM_RULE_NAME,
        "rule_name": LLM_RULE_NAME,
        "llm_used": llm_used,
    }
    if provider_id is not None:
        result["provider_id"] = provider_id
    if model is not None:
        result["model"] = model
    if images is not None:
        result["images"] = images
    if scope_key is not None:
        result["scope_key"] = scope_key
    if agent_turn_row_id is not None:
        result["agent_turn_row_id"] = agent_turn_row_id
    if cancelled_reason is not None:
        # 本轮在生成前被取消（如被动触发排队超耐心）：适配层据此跳过
        # 发送确认类副作用（冷却/统计），不得当作已发送。
        result["cancelled_reason"] = cancelled_reason
    return result


def image_caption_blob(descriptions: list[ImageDescription]) -> tuple[int, str]:
    """图注落库文本：单条截 200、整坨截 800，顺序 = 候选顺序（确定性）。

    截断必须在落库前完成——落库字节即前缀字节，下一轮换侧 history
    原样复现。
    """
    descs = [d.text_description.strip() for d in descriptions if d.text_description.strip()]
    blob = "；".join(d[:MAX_PERSISTED_IMAGE_DESC_CHARS].rstrip() for d in descs)
    return len(descs), blob[:MAX_PERSISTED_IMAGE_DESC_BLOB_CHARS]


def build_raw_turn_text(
    stored_prompt: str,
    *,
    quoted_text: str,
    quoted_image_urls: list[str],
    forward_text: str,
    forward_image_urls: list[str],
    image_descriptions: list[ImageDescription] | None,
) -> str:
    """触发行 ``raw_content`` 的唯一拼装（引用 / 转发 / 图注 + 正文）。

    agent 记录路径（begin_loop 的 UserTriggerPayload）与无记录落库路径
    （append_conversation_message）共用本实现，两条路径字节一致。
    """
    raw_turn_parts: list[str] = []
    if quoted_text or quoted_image_urls:
        q_text = quoted_text or f"[图片 {len(quoted_image_urls)} 张]"
        q_suffix = f" [附图 {len(quoted_image_urls)} 张]" if quoted_image_urls else ""
        raw_turn_parts.append(f"[引用] {q_text}{q_suffix}")
    if forward_text or forward_image_urls:
        fw_text = forward_text or "[合并转发消息]"
        fw_suffix = f" [附图 {len(forward_image_urls)} 张]" if forward_image_urls else ""
        raw_turn_parts.append(fw_text + fw_suffix)
    if image_descriptions:
        # 非 VLM 路径：图注以文本身份落库（媒体本体永不进前缀）；下一轮
        # 换侧 history 直接复用落库字节，转述内容不再随轮丢失
        caption_count, caption_blob = image_caption_blob(image_descriptions)
        if caption_count:
            raw_turn_parts.append(f"[图片 {caption_count} 张：{caption_blob}]")
    raw_turn_parts.append(stored_prompt)
    return "\n".join(raw_turn_parts)


@dataclass(slots=True)
class NormalizedTurnInput:
    """输入规范化的产物：主链各段消费的派生值在此单点持有。"""

    prompt: str
    stored_prompt: str
    trimmed_prompt: str
    quoted_text: str
    quoted_prompt: str
    analysis_prompt: str
    image_urls: list[str]
    quoted_image_urls: list[str]
    forward_text: str
    forward_image_urls: list[str]
    has_content: bool


def normalize_turn_input(
    request: ChatTurnRequest,
    *,
    max_prompt_chars: int,
) -> NormalizedTurnInput:
    """入口输入的规范化（strip / 语音并入 / 纯图默认问句 / 截断派生）。"""
    prompt = request.prompt.strip()
    normalized_raw_user_text = (
        None if request.raw_user_text is None else request.raw_user_text.strip()
    )
    image_urls = [url for url in (request.image_urls or []) if url.strip()]
    quoted_text = request.quoted_text.strip()
    quoted_image_urls = [url for url in (request.quoted_image_urls or []) if url.strip()]
    forward_text = request.forward_text.strip()
    forward_image_urls = [url for url in (request.forward_image_urls or []) if url.strip()]
    normalized_voice_text = request.voice_text.strip()
    if normalized_voice_text:
        prompt = "\n".join(item for item in [prompt, normalized_voice_text] if item).strip()
    if (
        not prompt
        and image_urls
        and not quoted_text
        and not quoted_image_urls
        and not forward_text
        and not forward_image_urls
    ):
        prompt = _EMPTY_IMAGE_PROMPT
    stored_prompt = (
        normalized_raw_user_text if normalized_raw_user_text is not None else prompt
    )[:max_prompt_chars]
    has_content = bool(
        prompt
        or quoted_text
        or image_urls
        or quoted_image_urls
        or forward_text
        or forward_image_urls
    )
    trimmed_prompt = prompt[:max_prompt_chars]
    quoted_prompt = quoted_text[:MAX_QUOTED_MESSAGE_CHARS]
    analysis_prompt = "\n".join(
        item for item in [stored_prompt, quoted_prompt] if item
    )[:max_prompt_chars]
    return NormalizedTurnInput(
        prompt=prompt,
        stored_prompt=stored_prompt,
        trimmed_prompt=trimmed_prompt,
        quoted_text=quoted_text,
        quoted_prompt=quoted_prompt,
        analysis_prompt=analysis_prompt,
        image_urls=image_urls,
        quoted_image_urls=quoted_image_urls,
        forward_text=forward_text,
        forward_image_urls=forward_image_urls,
        has_content=has_content,
    )


@dataclass(slots=True)
class TurnRequestAssembler:
    """当轮请求装配对象（``_assemble_request`` 闭包的显式替代）。

    首轮与预算降级重建复用同一实例；``assemble()`` 每次调用重取历史并
    重建信封 / messages（复用已消费的补丁快照），最新结果挂在本实例
    属性上（``history`` / ``scene_patch`` / ``turn_envelope`` /
    ``messages``），供调用方做账本计量与持久化——原闭包经 6 个
    nonlocal 重绑定外层变量的边界在此显式化。
    """

    # service 侧绑定可调用（窄缝：不传 LLMService 实例）
    load_history: Callable[..., tuple[
        list[dict[str, object]], list[dict[str, str]], list[dict[str, str]] | None,
        dict[str, list["LLMConversationMessage"]],
    ]]
    collect_mention_profiles: Callable[..., list[dict[str, str]]]
    build_turn_envelope: Callable[..., str]
    build_messages: Callable[..., list["LLMConversationMessage"]]

    # 会话与历史上下文
    chat_id: int | str
    chat_type: str
    scope_key: str
    settings: "ResolvedGroupSettings"
    sensitive: SensitiveFilter
    user_id: int | str
    sender_name: str
    message_id: str | None
    quoted_sender_name: str
    quoted_user_id: str
    epoch_key: "EpochKey"
    epoch_params: "EpochParams"
    provider: "ProviderConfig"
    scene_patch_snapshot: list[dict[str, str]] | None

    # 当轮消息材料（规范化后）
    mentioned_qq_ids: list[str] | None
    analysis_prompt: str
    trimmed_prompt: str
    quoted_prompt: str
    memories: list[dict[str, object]]
    effective_image_urls: list[str]
    recent_images_source: list[dict[str, str]] | None
    request_quoted_image_urls: list[str]
    request_forward_image_urls: list[str]
    quoted_is_bot_self: bool
    forward_text: str
    image_descriptions: list[ImageDescription]
    include_recent_images: bool
    is_non_vision: bool

    # 请求静态段（system_prompt 已含 session_preset 的渲染效果）
    tool_specs: list["LLMToolSpec"]
    builtin_search_active: bool
    system_prompt: str

    # 装配产物（assemble() 每次重建）
    history: list[dict[str, object]] = field(default_factory=list)
    participants: list[dict[str, str]] = field(default_factory=list)
    scene_patch: list[dict[str, str]] | None = None
    projected_segments: dict[str, list["LLMConversationMessage"]] = field(default_factory=dict)
    turn_envelope: str = ""
    messages: list["LLMConversationMessage"] = field(default_factory=list)

    def assemble(self) -> LLMRequest:
        """首轮和预算重建复用已消费的补丁，按最新历史重新去重。"""
        self.history, self.participants, self.scene_patch, self.projected_segments = (
            self.load_history(
                chat_id=self.chat_id,
                chat_type=self.chat_type,
                scope_key=self.scope_key,
                settings=self.settings,
                sensitive=self.sensitive,
                user_id=self.user_id,
                sender_name=self.sender_name,
                recent_messages=self.scene_patch_snapshot,
                message_id=self.message_id,
                quoted_sender_name=self.quoted_sender_name,
                quoted_user_id=self.quoted_user_id,
                epoch_key=self.epoch_key,
                epoch_params=self.epoch_params,
                provider=self.provider,
            )
        )
        mention_profiles = self.collect_mention_profiles(
            chat_id=self.chat_id,
            mentioned_qq_ids=self.mentioned_qq_ids or [],
            prompt=self.analysis_prompt or self.trimmed_prompt,
            quoted_text=self.quoted_prompt,
            forward_text=self.forward_text,
            history=self.history,
            scene_patch=self.scene_patch,
            current_user_id=str(self.user_id),
            quoted_user_id=self.quoted_user_id,
        )
        self.turn_envelope = self.build_turn_envelope(
            self.chat_id,
            self.chat_type,
            self.analysis_prompt or self.trimmed_prompt,
            self.memories,
            participants=self.participants,
            mention_profiles=mention_profiles,
        )
        self.messages = self.build_messages(
            prompt=self.trimmed_prompt,
            image_urls=self.effective_image_urls,
            history=self.history,
            recent_messages=self.scene_patch,
            recent_images_messages=self.recent_images_source,
            chat_type=self.chat_type,
            group_id=str(self.chat_id),
            current_sender_name=self.sender_name,
            current_user_id=str(self.user_id),
            quoted_text=self.quoted_prompt,
            quoted_sender_name=self.quoted_sender_name,
            quoted_user_id=self.quoted_user_id,
            quoted_image_urls=self.request_quoted_image_urls,
            quoted_is_bot_self=self.quoted_is_bot_self,
            forward_text=self.forward_text,
            forward_image_urls=self.request_forward_image_urls,
            image_descriptions=self.image_descriptions or None,
            include_recent_images=self.include_recent_images and not self.is_non_vision,
            turn_envelope=self.turn_envelope,
            projected_history_segments=self.projected_segments,
        )
        return LLMRequest(
            model=self.settings.model or self.provider.default_model,
            system_prompt=self.system_prompt,
            messages=self.messages,
            temperature=self.provider.temperature,
            max_output_tokens=self.provider.max_output_tokens,
            tools=self.tool_specs,
            allow_tool_calls=bool(self.tool_specs),
            tool_choice="auto",
            builtin_search=self.builtin_search_active,
        )


# 空正文且未放宽 allow_empty 时的兜底占位（用户可见，单一事实来源）。
EMPTY_REPLY_PLACEHOLDER = "模型没有返回可显示的文本。"


def finalize_reply_text(
    response: "LLMResponse",
    *,
    provider_id: str,
    model: str,
    sensitive: SensitiveFilter,
    scope_key: str,
    allow_empty: bool = False,
) -> str:
    """输出后处理：剥推理头、折叠空行、内置搜索来源块与敏感词输出扫描。

    敏感命中只观察不改变重试；blocked 时正文与落库共用 fallback 文本
    （毒化下一轮上下文的内容不落 history）。``allow_empty``：响应携带
    模型产出图片而无正文时保持空文本（占位提示会跟图片一起发给用户）。
    """
    text = strip_leading_reasoning_content(response.text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text and not allow_empty:
        text = EMPTY_REPLY_PLACEHOLDER

    if response.web_search is not None:
        logger.info(
            "LLM built-in web search: provider=%s model=%s queries=%s sources=%s",
            provider_id,
            model,
            response.web_search.queries,
            [source.url for source in response.web_search.sources],
        )
        text = append_web_search_source_block(text, response.web_search)

    if sensitive.is_loaded:
        output_scan = sensitive.scan(text)
        if output_scan.hits:
            _log_sensitive_hits("output", scope_key, output_scan)
        if output_scan.blocked:
            text = DEFAULT_OUTPUT_FALLBACK
    return text
